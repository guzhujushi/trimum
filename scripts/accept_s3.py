"""S3 真机验收（无需 sudo）：seccomp 三档**真的拦得住**，且只拦该拦的。

跑法（真机、以 guzhujushi 身份）：

    cd /home/guzhujushi/trimum && .venv/bin/python scripts/accept_s3.py

三条设计口径都是真机踩出来的（2026-09-22）：

* **判别器只选「正常会成功」的 syscall** —— ``ptrace(PTRACE_TRACEME)``（对照组 rc=0）与
  ``io_uring_setup``（对照组返回 fd）。``bpf`` / ``mount`` / ``setns`` 在非特权下**本来就
  失败**（EINVAL / ENOENT），拿它们验收会得出「拦住了」的**假结论**；
* **每条判据先跑对照组** —— 不施加过滤器时判据不成立，就直接判 FAIL：证据不成立时
  不许下结论；
* **能力口径是 API level**（``seccomp_api_get``），不是版本号 —— ``seccomp_version()``
  走 ctypes 读不出来（restype 试 c_uint / c_int / c_ulong 全是垃圾）。

全程用临时 ``TRIMUM_HOME``（不碰 ``~/.trimum``），不施加、不重启任何 daemon。
"""

from __future__ import annotations

import asyncio
import os
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


REPO = APP
PY = str(_interpreter())
HOME = Path(tempfile.mkdtemp(prefix="s3home-"))
WORK = Path(tempfile.mkdtemp(prefix="s3work-"))
SENTINEL = WORK / "TRM-S3-MUST-NOT-EXIST"
env = dict(os.environ, TRIMUM_HOME=str(HOME), PYTHONPATH=str(SRC), PYTHONIOENCODING="utf-8")
env.pop("TRIMUM_SECCOMP", None)

PASS: list[str] = []
FAIL: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    (PASS if condition else FAIL).append(label)
    mark = "ok  " if condition else "FAIL"
    print(f"[{mark}] {label}" + (f"  -- {detail}" if detail and not condition else ""))
    sys.stdout.flush()


def run(argv: list[str], timeout: float = 120.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv, cwd=str(REPO), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )


def _parse(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            out[parts[0]] = " ".join(parts[1:])
    return out


def _rc(entry: str) -> int:
    return int(entry.split("rc=")[1].split()[0])


def _errno(entry: str) -> int:
    return int(entry.split("errno=")[1].split()[0])


PROBE = """
import ctypes, os
libc = ctypes.CDLL(None, use_errno=True)
libc.syscall.restype = ctypes.c_long

class Params(ctypes.Structure):
    _fields_ = [("pad", ctypes.c_uint64 * 16)]

def probe(label, fn):
    ctypes.set_errno(0)
    rc = fn()
    print("%s rc=%d errno=%d" % (label, rc, ctypes.get_errno()))

params = Params()
probe("ptrace", lambda: libc.ptrace(0, 0, 0, 0))
probe("io_uring_setup", lambda: libc.syscall(__NR_IO_URING__, 2, ctypes.byref(params)))
probe("getpid", lambda: libc.getpid())
"""

SOCKET_PROBE = """
import socket
for label, family in (("inet", socket.AF_INET), ("unix", socket.AF_UNIX)):
    try:
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.close()
        print("%s ok" % label)
    except OSError as exc:
        print("%s errno=%d" % (label, exc.errno or 0))
"""


def syscall_nr(name: str) -> int:
    """本架构的 syscall 号（走 libseccomp 的名字表，不硬编码）。"""
    code = (
        "from trimum_core import seccomp_exec as s\n"
        f"print(s._resolver_default({name!r}, s.libc_library()))\n"
    )
    proc = run([PY, "-c", code])
    try:
        return int(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return -1


NR_IO_URING = syscall_nr("io_uring_setup")
NR_PTRACE = syscall_nr("ptrace")
PROBE_SCRIPT = PROBE.replace("__NR_IO_URING__", str(NR_IO_URING))


def plain(script: str) -> dict[str, str]:
    """对照组：**不施加**过滤器跑同一段脚本。"""
    return _parse(run([PY, "-c", script]).stdout)


def sandboxed(script: str, profile: str, *extra: str) -> tuple[subprocess.CompletedProcess, dict[str, str]]:
    proc = run(
        [PY, "-m", "trimum_core.seccomp_exec", "--profile", profile, *extra,
         "--", PY, "-c", script]
    )
    return proc, _parse(proc.stdout)


def status(*args: str) -> subprocess.CompletedProcess:
    return run([PY, "-m", "trimum_core.seccomp_exec", "--status", *args])


# ══════════════════════════════════════════════════════════════════════
# A. 能力与状态
# ══════════════════════════════════════════════════════════════════════

_print = print
print("== A. 能力与状态 ==")
cap = status()
check("A1 seccomp --status 退出码 0", cap.returncode == 0, cap.stderr[-200:])

api = 0
for line in cap.stdout.splitlines():
    if "api_level=" in line:
        api = int(line.split("api_level=")[1].split()[0])
check("A2 报出 API level（不是版本号）", api >= 1, f"api_level={api}")

check("A3 判据的 syscall 号解得出来", NR_PTRACE > 0 and NR_IO_URING > 0,
      f"ptrace={NR_PTRACE} io_uring_setup={NR_IO_URING}")

check("A4 默认档状态 = l1", "state      : l1" in cap.stdout, cap.stdout[-200:])

rules = [line for line in cap.stdout.splitlines() if "rule     :" in line]
check("A5 内置危险内核面整段都进了档案（>= 25 条）", len(rules) >= 25, f"rules={len(rules)}")
check("A6 清单里不含 §7.2 的两个非 syscall",
      not any(("swapcontext" in line or "poweroff(" in line) for line in rules))

# ══════════════════════════════════════════════════════════════════════
# B. 判据自证（对照组：不施加时这两条必须成功）
# ══════════════════════════════════════════════════════════════════════

print()
print("== B. 判据自证（对照组） ==")
base = plain(PROBE_SCRIPT)
check("B1 对照组 ptrace(TRACEME) 成功（rc=0 / errno=0）",
      _rc(base.get("ptrace", "rc=-1 errno=-1")) == 0 and _errno(base.get("ptrace", "rc=-1 errno=-1")) == 0,
      str(base))
check("B2 对照组 io_uring_setup 返回 fd（errno=0）",
      _errno(base.get("io_uring_setup", "rc=-1 errno=-1")) == 0
      and _rc(base.get("io_uring_setup", "rc=-1 errno=-1")) >= 0,
      str(base))
base_socket = plain(SOCKET_PROBE)
check("B3 对照组 AF_INET / AF_UNIX 都能建 socket",
      base_socket.get("inet") == "ok" and base_socket.get("unix") == "ok", str(base_socket))

# ══════════════════════════════════════════════════════════════════════
# C. l1 档：拦危险面，不碰良性 syscall
# ══════════════════════════════════════════════════════════════════════

print()
print("== C. l1 档 ==")
proc, got = sandboxed(PROBE_SCRIPT, "l1")
check("C1 l1 下命令本身跑得起来", proc.returncode == 0, proc.stderr[-200:])
check("C2 l1 拦住 ptrace(TRACEME)（EPERM=1）", _errno(got.get("ptrace", "")) == 1, str(got))
check("C3 l1 拦住 io_uring_setup（EPERM=1）", _errno(got.get("io_uring_setup", "")) == 1, str(got))
# getpid 每个进程都不一样，只断言「正常返回了正数」；别跟对照组比相等（首跑就是这么挂的）
check("C4 l1 不碰良性 syscall（getpid 正常返回且 errno=0）",
      _rc(got.get("getpid", "rc=-1 errno=-1")) > 0
      and _errno(got.get("getpid", "rc=-1 errno=-1")) == 0,
      f"{got.get('getpid')} vs 对照组 {base.get('getpid')}")

# ══════════════════════════════════════════════════════════════════════
# D. strict 档：再挡网络地址族，**AF_UNIX 是红线**（子 Agent 的 RPC 靠它）
# ══════════════════════════════════════════════════════════════════════

print()
print("== D. strict 档 ==")
proc, got_socket = sandboxed(SOCKET_PROBE, "strict")
check("D1 strict 下脚本本身跑得起来", proc.returncode == 0, proc.stderr[-200:])
check("D2 strict 挡 AF_INET（EPERM=1）", _errno(got_socket.get("inet", "")) == 1, str(got_socket))
check("D3 strict **放行** AF_UNIX（RPC 红线）", got_socket.get("unix") == "ok", str(got_socket))

_proc_s, got_strict = sandboxed(PROBE_SCRIPT, "strict")
check("D4 strict 是 l1 的超集（ptrace 仍被拦）", _errno(got_strict.get("ptrace", "")) == 1, str(got_strict))

# ══════════════════════════════════════════════════════════════════════
# E. off 档：一键退是整层的
# ══════════════════════════════════════════════════════════════════════

print()
print("== E. off 档 ==")
proc, got_off = sandboxed(PROBE_SCRIPT, "off")
check("E1 off 档一切照旧（与对照组一致）",
      _rc(got_off.get("ptrace", "rc=-1 errno=-1")) == _rc(base.get("ptrace", "rc=-1 errno=-1")) == 0,
      str(got_off))
check("E2 off 档 status 显示未施加",
      "off (seccomp 未施加)" in status("--profile", "off").stdout)

# ══════════════════════════════════════════════════════════════════════
# F. 白名单模式（只看档案，不施加 —— 基线只够跑静态小二进制）
# ══════════════════════════════════════════════════════════════════════

print()
print("== F. 白名单模式 ==")
wl = status("--profile", "strict", "--allow", "read")
check("F1 strict + 声明放行 ⇒ 白名单形态", "mode=whitelist" in wl.stdout, wl.stdout[-300:])
check("F2 白名单模式下默认动作是拒绝、规则全是 allow",
      "deny=0" in wl.stdout and "allow=" in wl.stdout, wl.stdout[-300:])
check("F3 非 strict 档给 allow 被忽略（那是放宽）",
      "只在 strict 档有效" in status("--profile", "l1", "--allow", "read").stdout)

# ══════════════════════════════════════════════════════════════════════
# G. S2 × S3 联动（Landlock + seccomp 一起施，落在**子进程**）
# ══════════════════════════════════════════════════════════════════════

print()
print("== G. S2 × S3 联动 ==")
sys.path.insert(0, str(SRC))
from trimum_core import sandbox_exec, seccomp_exec  # noqa: E402
from trimum_core.models import ExecuteRequest  # noqa: E402

req = ExecuteRequest(tool="shell", args=["echo hi"], cwd=str(WORK))
plan = sandbox_exec.plan_for(req)
check("G1 档案里同时带 Landlock 与 seccomp 两半", plan.seccomp is not None, str(plan.state))
check("G2 两个状态都回写到请求（审计要看）",
      req.sandbox == plan.state and req.seccomp == plan.seccomp_state,
      f"sandbox={req.sandbox!r} seccomp={req.seccomp!r}")

async def _spawn_probe() -> tuple[str, str]:
    child = await sandbox_exec.spawn_exec(
        plan, PY, "-c", PROBE_SCRIPT,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await child.communicate()
    return out.decode(), err.decode()

out, err = asyncio.run(_spawn_probe())
linked = _parse(out)
check("G3 spawn_exec 派生的子进程里 seccomp 真的在（ptrace EPERM）",
      _errno(linked.get("ptrace", "")) == 1, f"{out} {err}")
check("G4 联动后状态仍是成功档（没降级）",
      plan.state == "workspace-write" and plan.seccomp.state == "l1",
      f"{plan.state} / {plan.seccomp_state}")

mod = run([PY, "-m", "trimum_core.sandbox_exec", "--status"])
check("G5 sandbox_exec --status 两侧都摆上台面",
      "landlock" in mod.stdout.lower() and "seccomp" in mod.stdout.lower(), mod.stdout[-300:])

# ══════════════════════════════════════════════════════════════════════
# H. fail-closed 与「只收紧不放宽」
# ══════════════════════════════════════════════════════════════════════

print()
print("== H. fail-closed / 只收紧 ==")
# 必须写进 os.environ：plan_for 是**本进程**读环境变量，只改局部 env 字典它看不见
os.environ["TRIMUM_SECCOMP"] = env["TRIMUM_SECCOMP"] = "banana"
bad = sandbox_exec.plan_for(ExecuteRequest(tool="shell", args=["echo hi"], cwd=str(WORK)))
os.environ.pop("TRIMUM_SECCOMP", None)
env.pop("TRIMUM_SECCOMP", None)
check("H1 档位写错 ⇒ 档案不可用（blockers + :failed）",
      bool(bad.blockers) and bad.state.endswith(":failed"),
      f"{bad.blockers} / {bad.state}")

async def _blocked() -> str:
    try:
        await sandbox_exec.spawn_shell(bad, f"echo x > {SENTINEL}")
    except sandbox_exec.SandboxError:
        return "SandboxError"
    return "executed"

check("H2 档案不可用 ⇒ 命令**不执行**", asyncio.run(_blocked()) == "SandboxError")
check("H3 哨兵文件不存在（真的没跑）", not SENTINEL.exists())

from trimum_core.models import AgentManifest  # noqa: E402

tight = sandbox_exec.plan_for(
    {"agent_manifest": AgentManifest(name="p", version="1", capabilities=[],
                                     sandbox={"seccomp_profile": "strict"})},
    mode="workspace-write",
)
loose = sandbox_exec.plan_for(
    {"agent_manifest": AgentManifest(name="p", version="1", capabilities=[],
                                     sandbox={"seccomp_profile": "off"})},
    mode="workspace-write",
)
check("H4 包能把 seccomp 收紧（strict 生效）", tight.seccomp.profile == "strict", tight.seccomp.profile)
check("H5 包不能把 seccomp 放回 off（默认仍是 l1）", loose.seccomp.profile == "l1", loose.seccomp.profile)

# ══════════════════════════════════════════════════════════════════════
# I. 审计：一条**正常**命令也带着两个状态（沙箱没把正常活儿搞坏）
# ══════════════════════════════════════════════════════════════════════

print()
print("== I. 审计与正常命令 ==")
from trimum_core.tool_dispatchers import ShellDispatcher  # noqa: E402

resp = asyncio.run(
    ShellDispatcher().execute(ExecuteRequest(tool="shell", args=["echo", "s3-ok"], cwd=str(WORK)))
)
check("I1 正常命令在 l1 下照常跑通", "s3-ok" in (resp.output or ""), f"{resp.output!r} {resp.error!r}")
check("I2 审计里两个状态都在", bool(resp.sandbox) and bool(resp.seccomp),
      f"sandbox={resp.sandbox!r} seccomp={resp.seccomp!r}")
check("I3 seccomp 状态是 l1（真施上了，不是空串）", resp.seccomp == "l1", resp.seccomp)

print()
print(f"== S3 验收：{len(PASS)} passed / {len(FAIL)} failed ==")
for item in FAIL:
    print(f"  FAILED: {item}")
print(f"artifacts: TRIMUM_HOME={HOME} work={WORK}")
sys.exit(1 if FAIL else 0)
