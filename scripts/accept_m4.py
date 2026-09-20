"""M4 真机验收（无需 sudo）：隔离 daemon + IPC 生命周期 + HTTP 传输 + 空闲回收。

跑法（真机、以 guzhujushi 身份）：
    cd /home/guzhujushi/trimum && .venv/bin/python /tmp/accept_m4.py

用隔离的 config / socket / db / 日志起一个 8323 端口 daemon，不碰生产 daemon
（8321 + /run/user/1000/trimum.sock），跑完自动收摊。
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

APP = Path(os.environ.get("TRIMUM_APP_DIR", "/home/guzhujushi/trimum"))
def _interpreter() -> Path:
    """开发树是 `.venv/`，部署树 `/opt/trimum` 是 `venv/`。"""
    for name in (".venv", "venv"):
        candidate = APP / name / "bin" / "python"
        if candidate.exists():
            return candidate
    return Path(sys.executable)  # 兜底：用当前解释器


PY = _interpreter()
BASE = Path(os.environ.get("TRIMUM_ACCEPT_DIR", "/tmp/m4-accept"))
PORT = int(os.environ.get("TRIMUM_ACCEPT_PORT", "8323"))
MCP_DIR = BASE / "mcp"
CONFIG = BASE / "trimum.yaml"
IDLE_TTL = 5.0

PASS: list[str] = []
FAIL: list[str] = []


def check(condition: bool, label: str, detail: str = "") -> bool:
    if condition:
        PASS.append(label)
        print(f"  [PASS] {label}" + (f"  {detail}" if detail else ""), flush=True)
    else:
        FAIL.append(label)
        print(f"  [FAIL] {label}" + (f"  {detail}" if detail else ""), flush=True)
    return condition


def cli(*args: str) -> tuple[int, dict | None, str]:
    """跑一次 `trm --config ... <args>`，返回 (rc, --json 解析结果, 原始输出)。"""
    proc = subprocess.run(
        [str(PY), "-m", "trimum_core.cli", "--config", str(CONFIG), *args],
        cwd=str(APP),
        capture_output=True,
        text=True,
        env={**os.environ, "TRIMUM_MCP_DIR": str(MCP_DIR)},
    )
    raw = (proc.stdout or "") + (proc.stderr or "")
    data = None
    try:
        data = json.loads(proc.stdout)
    except Exception:
        data = None
    return proc.returncode, data, raw.strip()


def write_server(server: str, **payload) -> None:
    MCP_DIR.mkdir(parents=True, exist_ok=True)
    (MCP_DIR / f"{server}.json5").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def status() -> dict:
    rc, data, raw = cli("--json", "mcp", "status")
    if not isinstance(data, dict):
        raise SystemExit(f"mcp status 不是 JSON：rc={rc}\n{raw}")
    return data


def row(data: dict, name: str) -> dict:
    for item in data.get("servers", []):
        if item["server"] == name:
            return item
    raise SystemExit(f"status 里没有 {name}：{data}")


def main() -> int:
    if BASE.exists():
        shutil.rmtree(BASE)
    BASE.mkdir(parents=True)
    MCP_DIR.mkdir(parents=True)
    CONFIG.write_text(
        "\n".join(
            [
                "core:",
                "  host: 127.0.0.1",
                f"  port: {PORT}",
                f"  socket_path: {BASE}/trimum.sock",
                "logging:",
                "  level: INFO",
                f"  file: {BASE}/trimum.log",
                "context:",
                f"  db_path: {BASE}/context.db",
                "",
            ]
        ),
        encoding="utf-8",
    )

    echo = APP / "tests" / "fixtures" / "mcp_echo_server.py"
    write_server(
        "demo",
        name="demo",
        command=str(PY),
        args=[str(echo)],
        enabled=True,
        timeout=10.0,
        idle_ttl=IDLE_TTL,
        max_memory_mb=256,
        max_cpu_percent=25,
    )

    log = (BASE / "daemon.log").open("wb")
    daemon = subprocess.Popen(
        [str(PY), "-m", "trimum_core.main", "--config", str(CONFIG)],
        cwd=str(APP),
        stdout=log,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        env={**os.environ, "TRIMUM_MCP_DIR": str(MCP_DIR)},
    )
    httpd = None
    try:
        print("== 隔离 daemon 启动 ==", flush=True)
        deadline = time.time() + 30
        data = None
        while time.time() < deadline:
            probe = None
            try:
                probe = status()
            except SystemExit:
                probe = None
            if isinstance(probe, dict) and probe.get("source") == "daemon":
                data = probe
                break
            time.sleep(1.0)
        if not check(data is not None, f"隔离 daemon 起来并可走 IPC（pid={daemon.pid}）"):
            print((BASE / "daemon.log").read_text(encoding="utf-8", errors="replace")[-2000:])
            return 1
        check(data["source"] == "daemon", "mcp.status 来自 daemon 的共享池", f"source={data['source']}")
        check(data["running"] == 0, "接线后没有任何 server 被提前拉起", f"running={data['running']}")

        print("== mcp.restart（IPC）==", flush=True)
        rc, out, raw = cli("--json", "mcp", "restart", "demo")
        check(rc == 0 and isinstance(out, dict) and out.get("success"), "mcp.restart demo 成功", raw)
        first = status()
        demo = row(first, "demo")
        check(demo["connected"] is True, "restart 之后 demo 在跑", f"pid={demo.get('pid')}")
        pid1 = demo.get("pid")
        check(isinstance(pid1, int) and pid1 > 0, "status 报出真实 pid", f"pid={pid1}")
        check(demo.get("idle_ttl") == IDLE_TTL, "status 报出 idle_ttl", f"idle_ttl={demo.get('idle_ttl')}")
        print(f"  [info] cgroup 状态：{demo.get('cgroup')!r}", flush=True)

        rc, out, raw = cli("--json", "mcp", "restart", "demo")
        pid2 = row(status(), "demo").get("pid")
        check(rc == 0 and pid2 != pid1, "restart 真的是停旧起新（pid 变了）", f"{pid1} -> {pid2}")

        print("== streamable-http 传输 ==", flush=True)
        sys.path.insert(0, str(APP / "tests"))
        from fixtures.mcp_http_server import start_server  # noqa: PLC0415

        httpd = start_server()
        write_server(
            "httpdemo",
            name="httpdemo",
            transport="http",
            url=httpd.url,
            enabled=True,
            timeout=10.0,
            idle_ttl=300.0,
        )
        rc, out, raw = cli("--json", "mcp", "restart", "httpdemo")
        check(rc == 0 and isinstance(out, dict) and out.get("success"), "mcp.restart httpdemo 成功", raw)
        http_row = row(status(), "httpdemo")
        check(http_row["connected"] is True, "HTTP server 连上了", f"url={httpd.url}")
        check(http_row["transport"] == "http", "status 报出 http 传输", f"transport={http_row['transport']}")
        rc, out, raw = cli("--json", "mcp", "tools", "httpdemo")
        names = sorted(t["name"] for s in (out or {}).get("servers", []) for t in s.get("tools", []))
        check(rc == 0 and "echo" in names, "HTTP 传输能列工具（真协议往返）", f"tools={names}")

        print(f"== 空闲回收（idle_ttl={IDLE_TTL}s，回收器 30s 扫一轮）==", flush=True)
        check(row(status(), "demo")["connected"] is True, "回收前 demo 在跑")
        time.sleep(IDLE_TTL + 32)
        after = status()
        check(row(after, "demo")["connected"] is False, "空闲超时后 demo 被回收")
        check(row(after, "httpdemo")["connected"] is True, "idle_ttl=300 的 httpdemo 不受影响")

        rc, out, raw = cli("mcp", "restart", "ghost")
        check(rc == 1 and "not found" in raw, "不存在的 server 报错而不是静默成功", raw.splitlines()[-1])
    finally:
        print("== 收摊 ==", flush=True)
        if httpd is not None:
            httpd.stop()
        daemon.send_signal(signal.SIGTERM)
        try:
            daemon.wait(timeout=15)
        except subprocess.TimeoutExpired:
            daemon.kill()
            daemon.wait(timeout=10)
        log.close()
        print(f"  daemon 退出码 {daemon.returncode}", flush=True)
        shutil.rmtree(BASE, ignore_errors=True)

    print(f"\n== M4 真机验收：{len(PASS)} PASS / {len(FAIL)} FAIL ==", flush=True)
    for label in FAIL:
        print(f"  [FAIL] {label}")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
