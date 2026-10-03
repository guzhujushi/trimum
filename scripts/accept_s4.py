"""S4 真机验收（无需 sudo）：`systemd-run --user` 资源边界**真的拦得住**，且如实降级。

跑法（真机、以 guzhujushi 身份）：

    cd /home/guzhujushi/trimum && .venv/bin/python scripts/accept_s4.py

口径全部是 2026-09-27 真机实测出来的：

* `systemd-run --user --quiet --wait --pipe --collect -p ... -- <cmd>` 里 `--wait --pipe`
  是唯一可信口径（不带 `--wait` 测到的是竞态）；
* **只设 `MemoryMax` 不够** —— 本机 4 GiB swap，灌 200 MiB 照样成功；必须同时
  `MemorySwapMax=0` 才 `oom-kill`（B3 专门把这行摊开打印）；
* `unsupported` 是**如实降级**（argv 原样、一个 `-p` 都不加），不是失败（C2/C5）。

S4 不接线：只验 `sandbox_limits` 的纯计算 + 真跑构造出的 argv，不碰
agent_loop / daemon / CLI / ToolGateway。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

APP = Path(os.environ.get("TRIMUM_APP_DIR", Path(__file__).resolve().parents[1]))
SRC = APP / "src"


def _interpreter() -> Path:
    """开发树是 `.venv/`，部署树 `/opt/trimum` 是 `venv/`。"""
    for name in (".venv", "venv"):
        candidate = APP / name / "bin" / "python"
        if candidate.exists():
            return candidate
    return Path(sys.executable)  # 兜底：用当前解释器


PY = str(_interpreter())
WORK = Path(tempfile.mkdtemp(prefix="s4work-"))
env = dict(os.environ, PYTHONPATH=str(SRC), PYTHONIOENCODING="utf-8")

PASS: list[str] = []
FAIL: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    (PASS if condition else FAIL).append(label)
    mark = "ok  " if condition else "FAIL"
    print(f"[{mark}] {label}" + (f"  -- {detail}" if detail and not condition else ""))
    sys.stdout.flush()


def run(argv: list[str], timeout: float = 120.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv, cwd=str(APP), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )


sys.path.insert(0, str(SRC))
from trimum_core import sandbox_limits as sl  # noqa: E402

HOG = 'import sys; s = b"a" * (200*1024*1024); print("hog-done", flush=True); sys.stdout.flush()'

# ══════════════════════════════════════════════════════════════════════
# A. 对照组：包出来的命令对正常命令无害
# ══════════════════════════════════════════════════════════════════════

print("== A. 对照组 ==")
ctl = sl.build_command(["/bin/bash", "-c", "echo s4-ok"], "ctl",
                       sl.Limits(memory_max_bytes=256 << 20))
check("A1.1 对照组构造走 systemd 档", ctl.state == sl.STATE_SYSTEMD and ctl.unit is not None,
      f"{ctl.state} / {ctl.unit}")
proc = run(list(ctl.argv))
check("A1.2 对照组真跑 rc==0 且 stdout 含 s4-ok",
      proc.returncode == 0 and "s4-ok" in proc.stdout,
      f"rc={proc.returncode} out={proc.stdout!r} err={proc.stderr!r}")
check("A2  --wait 与 --pipe 同时存在，且 -- 在 -p 之后、原 argv 之前",
      "--wait" in ctl.argv and "--pipe" in ctl.argv
      and ctl.argv.index("--") > ctl.argv.index("-p")
      and list(ctl.argv[ctl.argv.index("--") + 1 :]) == ["/bin/bash", "-c", "echo s4-ok"],
      " ".join(ctl.argv))

# ══════════════════════════════════════════════════════════════════════
# B. 真拦：内存上限真的 oom-kill
# ══════════════════════════════════════════════════════════════════════

print()
print("== B. 真拦（内存）==")
tight = sl.build_command([sys.executable, "-c", HOG], "hog",
                         sl.Limits(memory_max_bytes=32 << 20, memory_swap_max_bytes=0))
proc = run(list(tight.argv))
check("B1 32 MiB + swap=0 灌 200 MiB：rc!=0 且 stdout 不含 hog-done",
      proc.returncode != 0 and "hog-done" not in proc.stdout,
      f"rc={proc.returncode} out={proc.stdout!r} err={proc.stderr!r}")

loose = sl.build_command([sys.executable, "-c", HOG], "hog",
                         sl.Limits(memory_max_bytes=1 << 30, memory_swap_max_bytes=0))
proc = run(list(loose.argv))
check("B2 判别力对照：同一条命令、上限 1 GiB ⇒ rc==0 且含 hog-done",
      proc.returncode == 0 and "hog-done" in proc.stdout,
      f"rc={proc.returncode} out={proc.stdout!r} err={proc.stderr!r}")

noswap = sl.build_command(
    [sys.executable, "-c", HOG], "hog",
    sl.Limits(memory_max_bytes=32 << 20, memory_swap_max_bytes=1 << 30))
proc = run(list(noswap.argv))
print(f"INFO  B3 只设 MemoryMax=32 MiB（不限 swap）：rc={proc.returncode} "
      f"hog-done={'yes' if 'hog-done' in proc.stdout else 'no'}"
      f"（本机 4 GiB swap，不会被杀）—— 所以模块必须成对产出 MemoryMax + MemorySwapMax")

RES_PROBE = (
    "base=$(awk -F: '{print $3}' /proc/self/cgroup); "
    'echo "PIDS=$(cat /sys/fs/cgroup$base/pids.max)"; '
    'echo "CPU=$(cat /sys/fs/cgroup$base/cpu.max)"; '
    "grep NoNewPrivs /proc/self/status"
)
res = sl.build_command(["/bin/bash", "-c", RES_PROBE],
                       "res", sl.Limits(cpu_quota_percent=50, tasks_max=64))
proc = run(list(res.argv))
kv = dict(line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line)
check("B4.1 pids.max == 64（TasksMax=64）", kv.get("PIDS", "").strip() == "64", proc.stdout)
check("B4.2 cpu.max == '50000 100000'（CPUQuota=50%）",
      kv.get("CPU", "").split() == ["50000", "100000"], proc.stdout)
check("B4.3 NoNewPrivs: 1", "NoNewPrivs:\t1" in proc.stdout or "NoNewPrivs: 1" in proc.stdout,
      proc.stdout)

# ══════════════════════════════════════════════════════════════════════
# C. 纯计算：argv / 单元名 / 降级 / 非法档
# ══════════════════════════════════════════════════════════════════════

print()
print("== C. 纯计算 ==")
cmd = sl.build_command(["/bin/true"], "coder", systemd_ok=True)
check("C1 前 8 项口径",
      list(cmd.argv[:8]) == ["systemd-run", "--user", "--quiet", "--wait", "--pipe",
                             "--collect", "--unit=trimum-agent-coder.service", "-p"],
      " ".join(cmd.argv[:8]))

orig = ["echo", "degraded", "arg with space"]
deg = sl.build_command(orig, "x", systemd_ok=False)
check("C2 降级：state=unsupported、argv 逐项原样、unit is None",
      deg.state == "unsupported" and list(deg.argv) == orig and deg.unit is None,
      f"{deg.state} {deg.argv} {deg.unit}")

names = ["a b", "中文名字", "a/b", "x" * 300]
ok = True
detail = []
for name in names:
    unit = sl.unit_name(name)
    good = re.fullmatch(r"[A-Za-z0-9:_.-]+", unit) is not None and len(unit) <= 255
    ok = ok and good
    detail.append(f"{name!r:.20}→{unit[:30]}({len(unit)})")
check("C3 unit_name 空格/中文/斜杠/300 超长 ⇒ 合法字符且 ≤255", ok, "; ".join(detail))

bad_ok = True
bad_detail = []
for kwargs in ({"memory_max_bytes": 0}, {"cpu_quota_percent": 0}, {"tasks_max": 0}):
    try:
        sl.Limits(**kwargs)
        bad_ok = False
        bad_detail.append(f"{kwargs} 没抛")
    except ValueError as exc:
        bad_detail.append(str(exc))
check("C4 非法 Limits（0 档）抛 ValueError", bad_ok, "; ".join(bad_detail))

probe_src = "from trimum_core import sandbox_limits as s\nprint(s.current_state())\n"
probe = subprocess.run(
    [sys.executable, "-c", probe_src],
    cwd=str(APP),
    env=dict(os.environ, PYTHONPATH=str(SRC), PATH="/nonexistent",
             PYTHONIOENCODING="utf-8"),
    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
)
check("C5 降级实测：PATH=/nonexistent ⇒ current_state() == unsupported",
      probe.stdout.strip() == "unsupported",
      f"out={probe.stdout!r} rc={probe.returncode}")

print()
print(f"== S4 验收：{len(PASS)} passed / {len(FAIL)} failed ==")
for item in FAIL:
    print(f"  FAILED: {item}")
print("已知取舍：本机 bwrap 当前坏在 'mountinfo path is not absolute'（与本片无关，别去修）。")
print(f"artifacts: work={WORK}")
sys.exit(1 if FAIL else 0)
