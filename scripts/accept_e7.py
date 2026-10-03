"""E7 真机验收（无需 sudo）：编码会话编排 + CLI 子模式。

跑法（真机、以 guzhujushi 身份）：

    cd /home/guzhujushi/trimum && .venv/bin/python scripts/accept_e7.py

本脚本**不写** `~/.trimum`（F1/F2 的 CLI 默认家目录会**读**它的 `.env`，但不落盘）、
不起 daemon、不用 sudo；除 F4（显式 opt-in）外**不出网**（F3 用假 key + 不可达端点）。
全程 `TRIMUM_HOME` / `HOME` 指向临时目录；临时目录跑完自动清，`TRIMUM_ACCEPT_E7_KEEP=1` 可保留。
"""

from __future__ import annotations

import asyncio
import atexit
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

APP = Path(os.environ.get("TRIMUM_APP_DIR", Path(__file__).resolve().parents[1]))
SRC = APP / "src"


def _interpreter() -> Path:
    for name in (".venv", "venv"):
        candidate = APP / name / "bin" / "python"
        if candidate.exists():
            return candidate
    return Path(sys.executable)


REPO = APP
PY = str(_interpreter())
HOME = Path(tempfile.mkdtemp(prefix="e7home-"))
WORK = Path(tempfile.mkdtemp(prefix="e7work-"))
# 临时目录由脚本自己负责清（`TRIMUM_ACCEPT_E7_KEEP=1` 可保留下来排查）。
_TEMP_DIRS: list[Path] = [HOME, WORK]


def _cleanup_temps() -> None:
    if os.environ.get("TRIMUM_ACCEPT_E7_KEEP") == "1":
        print(f"保留临时目录（TRIMUM_ACCEPT_E7_KEEP=1）：{HOME} {WORK}")
        return
    for path in _TEMP_DIRS:
        shutil.rmtree(path, ignore_errors=True)


atexit.register(_cleanup_temps)
env = dict(os.environ, TRIMUM_HOME=str(HOME), PYTHONPATH=str(SRC), PYTHONIOENCODING="utf-8")
# 进程内 import 的是 trimum_core；必须把 TRIMUM_HOME 写回 os.environ，
# 否则 trimum_core 会回退到 ~/.trimum（只影响子进程 env 不够）。
os.environ["TRIMUM_HOME"] = str(HOME)
sys.path.insert(0, str(SRC))

from trimum_core import coding_agent  # noqa: E402
from trimum_core import patch_ops  # noqa: E402
from trimum_core import verifier  # noqa: E402

PASS: list[str] = []
FAIL: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    (PASS if condition else FAIL).append(label)
    mark = "ok  " if condition else "FAIL"
    print(f"[{mark}] {label}" + (f"  -- {detail}" if detail and not condition else ""))
    sys.stdout.flush()


def run(argv: list[str], timeout: float = 120.0) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=str(REPO), env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def run_cli(argv: list[str], sub_env: dict | None = None, cwd: Path | None = None,
            timeout: float = 120.0) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=str(cwd or REPO), env=sub_env or env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=timeout)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def purge_pycache(root: Path) -> None:
    """清掉 ``__pycache__`` —— pytest 的断言重写缓存按 **(mtime, size)** 判新旧。

    同一秒内、等长的两次编辑（C2 把 ``assert 2 == 2`` 改成 ``assert 2 == 3``）会命中
    C1 写下的旧 ``.pyc`` ⇒ 拿到**假绿**（2026-09-29 真机实测）。真机验收必须每次
    编辑后清一次，否则红的用例会被缓存洗白。
    """
    for cache in root.rglob("__pycache__"):
        for item in cache.iterdir():
            item.unlink()
        cache.rmdir()


def run_session(task: str, steps: list, cwd: Path = WORK, **kwargs):
    planner = coding_agent.ScriptedPlanner(steps)
    session = coding_agent.CodingSession(
        task,
        cwd=str(cwd),
        planner=planner,
        **kwargs,
    )
    return asyncio.run(session.run())


note = WORK / "note.txt"

# ── A 只读任务 ─────────────────────────────────────────────
note.write_text("ALPHA\n", encoding="utf-8")
sha_a = sha256(note)
rec_a = run_session(
    "只读：cat note.txt",
    [
        coding_agent.CodingStep(kind="run", command="cat note.txt"),
        coding_agent.CodingStep(kind="done"),
    ],
    yes=False,
)
check("A record.ok", rec_a.ok is True, detail=f"reason={rec_a.reason}")
check("A changes 为空", rec_a.changes == [])
check("A note.txt 未被改动", sha256(note) == sha_a)
check("A steps[0].status == ok",
      bool(rec_a.steps) and rec_a.steps[0].get("status") == "ok",
      detail=f"steps={rec_a.steps[:1]}")
check("A steps[0].output 含 ALPHA",
      bool(rec_a.steps) and "ALPHA" in str(rec_a.steps[0].get("output", "")))

# ── B 小改动任务（落盘）───────────────────────────────────
rec_b = run_session(
    "把 note.txt 的 ALPHA 改成 BETA",
    [
        coding_agent.CodingStep(kind="edit", path="note.txt", anchor="ALPHA",
                                replacement="BETA", reason="改名"),
        coding_agent.CodingStep(kind="done"),
    ],
    yes=True,
    dry_run=False,
)
sid_b = rec_b.session_id
check("B record.ok", rec_b.ok is True, detail=f"reason={rec_b.reason}")
check("B changes 非空", len(rec_b.changes) >= 1,
      detail=f"changes={[(c.path, c.status) for c in rec_b.changes]}")
if rec_b.changes:
    ch = rec_b.changes[0]
    check("B changes[0].status == applied", ch.status == "applied", detail=f"status={ch.status}")
    check("B added/removed 均 > 0", ch.added_lines > 0 and ch.removed_lines > 0,
          detail=f"added={ch.added_lines} removed={ch.removed_lines}")
    check("B snapshot_id 非空", bool(ch.snapshot_id))
else:
    check("B changes[0].status == applied", False, "no changes")
    check("B added/removed 均 > 0", False, "no changes")
    check("B snapshot_id 非空", False, "no changes")
sha_b = sha256(note)
check("B 文件含 BETA", "BETA" in note.read_text(encoding="utf-8"))
check("B sha_b != sha_a", sha_b != sha_a)
coding_json = HOME / "sessions" / sid_b / "coding.json"
session_json = HOME / "sessions" / sid_b / "session.json"
check("B coding.json 存在", coding_json.exists())
check("B session.json 存在", session_json.exists())
check("B 两记录同目录", coding_json.parent == session_json.parent)
coding_loadable = False
if coding_json.exists():
    try:
        json.loads(coding_json.read_text(encoding="utf-8"))
        coding_loadable = True
    except Exception:  # noqa: BLE001
        coding_loadable = False
check("B coding.json 可 json.load", coding_loadable)

# ── C 测试驱动任务（绿 + 红，真跑 pytest）──────────────────
proj = WORK / "proj"
(proj / "tests").mkdir(parents=True)
(proj / "pyproject.toml").write_text('[project]\nname="probe"\nversion="0"\n', encoding="utf-8")
(proj / "tests" / "test_probe.py").write_text("def test_ok(): assert 1 == 1\n", encoding="utf-8")
venv_bin = proj / ".venv" / "bin"
venv_bin.mkdir(parents=True)
shim = venv_bin / "python"
shim.write_text(f'#!/bin/sh\nexec "{PY}" "$@"\n', encoding="utf-8")
shim.chmod(0o755)
ctrl = subprocess.run([str(shim), "-m", "pytest", "-q"], cwd=str(proj),
                      capture_output=True, text=True, timeout=120.0)
check("C 对照组 pytest rc==0", ctrl.returncode == 0,
      detail=f"rc={ctrl.returncode} stderr={ctrl.stderr[-300:]}")
if ctrl.returncode != 0:
    check("C detect_project_specs 命中 .venv/bin/python", False, "对照组失败，本组中止")
    check("C detect_project_specs 命中 -m pytest", False, "对照组失败，本组中止")
else:
    specs = verifier.detect_project_specs(proj)
    spec_cmds = " ".join(" ".join(s.command) for s in specs)
    check("C detect_project_specs 命中 .venv/bin/python", ".venv/bin/python" in spec_cmds,
          detail=spec_cmds)
    check("C detect_project_specs 命中 -m pytest", "-m pytest" in spec_cmds, detail=spec_cmds)

    purge_pycache(proj)
    rec_c1 = run_session(
        "C1：给 proj 加一个通过的测试",
        [
            coding_agent.CodingStep(
                kind="edit", path="tests/test_probe.py",
                anchor="def test_ok(): assert 1 == 1",
                replacement="def test_ok(): assert 1 == 1\n\n\ndef test_added(): assert 2 == 2",
                reason="加测试"),
            coding_agent.CodingStep(kind="done"),
        ],
        cwd=proj,
        yes=True,
    )
    check("C1 verifications >= 1", len(rec_c1.verifications) >= 1,
          detail=f"n={len(rec_c1.verifications)}")
    if rec_c1.verifications:
        v1 = rec_c1.verifications[0]
        check("C1 verdict == green", v1.verdict == "green", detail=f"verdict={v1.verdict}")
        check("C1 exit_code == 0", v1.exit_code == 0, detail=f"exit_code={v1.exit_code}")
    else:
        check("C1 verdict == green", False, "no verifications")
        check("C1 exit_code == 0", False, "no verifications")
    check("C1 record.ok", rec_c1.ok is True, detail=f"reason={rec_c1.reason}")

    purge_pycache(proj)  # 不清就会命中 C1 的旧 .pyc ⇒ C2 假绿
    rec_c2 = run_session(
        "C2：把 test_added 改红",
        [
            coding_agent.CodingStep(kind="edit", path="tests/test_probe.py",
                                    anchor="assert 2 == 2", replacement="assert 2 == 3",
                                    reason="改红"),
            coding_agent.CodingStep(kind="done"),
        ],
        cwd=proj,
        yes=True,
    )
    check("C2 verifications >= 1", len(rec_c2.verifications) >= 1,
          detail=f"n={len(rec_c2.verifications)}")
    if rec_c2.verifications:
        v2 = rec_c2.verifications[0]
        check("C2 verdict == red", v2.verdict == "red", detail=f"verdict={v2.verdict}")
        check("C2 failures 非空", len(v2.failures) > 0, detail=f"failures={v2.failures[:1]}")
        check("C2 failures[0].file 指向 test_probe.py",
              bool(v2.failures) and "test_probe.py" in (v2.failures[0].file or ""),
              detail=f"file={v2.failures[0].file if v2.failures else None}")
    else:
        check("C2 verdict == red", False, "no verifications")
        check("C2 failures 非空", False, "no verifications")
        check("C2 failures[0].file 指向 test_probe.py", False, "no verifications")
    check("C2 record.ok is False", rec_c2.ok is False)
    check("C2 reason == verification_red", rec_c2.reason == "verification_red",
          detail=f"reason={rec_c2.reason}")

# ── D 越界拒绝 ─────────────────────────────────────────────
secret = WORK / "secret.pem"
gitconfig = WORK / ".git" / "config"
gitconfig.parent.mkdir(parents=True, exist_ok=True)
secret.write_text("SECRET\n", encoding="utf-8")
gitconfig.write_text("inner\n", encoding="utf-8")
sha_secret = sha256(secret)
sha_gitconfig = sha256(gitconfig)

check("D is_protected_path(secret.pem)", patch_ops.is_protected_path(secret))
check("D is_protected_path(.git/config)", patch_ops.is_protected_path(gitconfig))

for target, anchor, label in ((secret, "SECRET", "D1 secret.pem"),
                              (gitconfig, "inner", "D2 .git/config")):
    try:
        rec_d = run_session(
            f"{label}：越界编辑",
            [
                coding_agent.CodingStep(kind="edit", path=str(target), anchor=anchor,
                                        replacement="PWNED", reason="越界"),
                coding_agent.CodingStep(kind="done"),
            ],
            yes=True,
        )
        check(f"{label} 不抛异常", True)
        check(f"{label} changes[0].status == rejected",
              len(rec_d.changes) >= 1 and rec_d.changes[0].status == "rejected",
              detail=f"changes={[(c.path, c.status) for c in rec_d.changes]}")
        check(f"{label} record.ok is False", rec_d.ok is False)
        check(f"{label} reason == change_rejected", rec_d.reason == "change_rejected",
              detail=f"reason={rec_d.reason}")
    except Exception as exc:  # noqa: BLE001
        check(f"{label} 不抛异常", False, detail=repr(exc))
        check(f"{label} changes[0].status == rejected", False, detail=repr(exc))
        check(f"{label} record.ok is False", False, detail=repr(exc))
        check(f"{label} reason == change_rejected", False, detail=repr(exc))

check("D secret.pem sha 不变", sha256(secret) == sha_secret)
check("D .git/config sha 不变", sha256(gitconfig) == sha_gitconfig)

# ── E 回滚 ─────────────────────────────────────────────────
try:
    rolled = patch_ops.rollback(sid_b)
    check("E rollback 返回路径非空", len(rolled) > 0, detail=f"rolled={rolled}")
except Exception as exc:  # noqa: BLE001
    check("E rollback 返回路径非空", False, detail=repr(exc))
sha_e = sha256(note)
print(f"E note.txt sha: 原始 sha_a={sha_a}")
print(f"E note.txt sha: 改动后 sha_b={sha_b}")
print(f"E note.txt sha: 回滚后 sha_e={sha_e}")
check("E 回滚后 sha == sha_a", sha_e == sha_a)

# ── F CLI 真链路 ───────────────────────────────────────────
# F1 --skill 不存在
r_f1 = run_cli([PY, "-m", "trimum_core.cli", "exec", "--code", "x", "--skill", "no-such-skill"],
               cwd=WORK)
check("F1 退出码非 0", r_f1.returncode != 0, detail=f"rc={r_f1.returncode}")
check("F1 stderr 含 skill not found", "skill not found" in r_f1.stderr,
      detail=f"stderr={r_f1.stderr[-300:]}")

# F2 模式混用（对照组：同一条命令**不带** --yes 必须成功 ⇒ 证明失败是 flag 引起的）
r_f2_ctl = run_cli([PY, "-m", "trimum_core.cli", "exec", "echo", "hi"], cwd=WORK)
check("F2 对照组：不带 --yes 的同一条命令成功", r_f2_ctl.returncode == 0
      and "hi" in r_f2_ctl.stdout, detail=f"rc={r_f2_ctl.returncode} out={r_f2_ctl.stdout[-200:]}")
r_f2 = run_cli([PY, "-m", "trimum_core.cli", "exec", "--yes", "echo hi"], cwd=WORK)
check("F2 退出码非 0", r_f2.returncode != 0, detail=f"rc={r_f2.returncode}")
check("F2 stderr 含 只在 --code 模式", "只在 --code 模式" in r_f2.stderr,
      detail=f"stderr={r_f2.stderr[-300:]}")

# F3 没有模型
f3_home = Path(tempfile.mkdtemp(prefix="e7home-f3-"))
_TEMP_DIRS.append(f3_home)
sub_env = {k: v for k, v in env.items()
           if not any(t in k.upper() for t in ("LLM", "API_KEY", "OPENAI", "DEEPSEEK",
                                               "QWEN", "SJTU", "ANTHROPIC", "MOONSHOT"))}
sub_env["TRIMUM_HOME"] = str(f3_home)
# HOME 也必须换掉：`env_file.py` 里 `candidate_paths()` 硬编码 `~/.trimum/.env`，
# 只改 TRIMUM_HOME 的话真机的 `~/.trimum/.env`（含 DEEPSEEK_API_KEY / TRIMUM_LLM_*）
# 仍会被 `ensure_loaded` 读进 os.environ ⇒ 根本到不了「没有 key」那一步，
# 这两条判据就成了「验不出有没有删干净」（2026-09-29 验收窗口实测：M7 去掉剥离仍 49/0）。
f3_home.mkdir(parents=True, exist_ok=True)
sub_env["HOME"] = str(f3_home)
# 对照组（**离线、确定性**）：往「临时 HOME 的 ~/.trimum/.env」塞假 key + 不可达端点 ⇒
# 必须**不是**「缺少 API key」——证明 HOME 下的 `.env` 真会被 `ensure_loaded` 读进去，
# 所以「换掉 HOME」才是 load-bearing 的那一步。（拿真 HOME 跑一次也能看出来，但那会真的
# 调一次模型：要么拿到输出、要么「模型输出无法解析」，是网络相关的不确定证据。）
ctl_home = Path(tempfile.mkdtemp(prefix="e7home-f3ctl-"))
_TEMP_DIRS.append(ctl_home)
(ctl_home / ".trimum").mkdir(parents=True, exist_ok=True)
(ctl_home / ".trimum" / ".env").write_text(
    "JIAOWOISAN_API_KEY=fake-control\nDEEPSEEK_API_KEY=fake-control\n"
    "TRIMUM_LLM_BASE_URL=http://127.0.0.1:9/v1\nTRIMUM_LLM_FALLBACK_ENABLED=0\n",
    encoding="utf-8",
)
ctl_env = dict(sub_env)
ctl_env["HOME"] = str(ctl_home)
r_f3_ctl = run_cli([PY, "-m", "trimum_core.cli", "exec", "--code", "x", "--yes", "--json"],
                   sub_env=ctl_env, cwd=WORK)
_ctl = r_f3_ctl.stdout + r_f3_ctl.stderr
check("F3 对照组：临时 HOME 里的 .env 被读到（所以换 HOME 才是 load-bearing）",
      "缺少 API key" not in _ctl, detail=_ctl[-300:])
check("F3 对照组：假 key + 不可达端点 ⇒ 也是非零退出（没有模型不许假装完成）",
      r_f3_ctl.returncode != 0, detail=f"rc={r_f3_ctl.returncode}")
# 反向对照：换掉 HOME ⇒ 必须落在「没有可用的模型 / 缺少 API key」上，而不是别的失败原因
r_f3 = run_cli([PY, "-m", "trimum_core.cli", "exec", "--code",
                "把 note.txt 里的 ALPHA 改成 BETA", "--yes", "--json"],
               sub_env=sub_env, cwd=WORK)
_f3 = r_f3.stdout + r_f3.stderr
check("F3 换 HOME 后真的落在「没有可用的模型」上",
      "无法开始" in _f3 and ("缺少 API key" in _f3 or "没有可用的模型" in _f3),
      detail=_f3[-400:])
check("F3 退出码非 0（没有模型不能假装完成）", r_f3.returncode != 0,
      detail=f"rc={r_f3.returncode}")
combined_f3 = r_f3.stdout + r_f3.stderr
check("F3 输出含 无法开始/NoModel", ("无法开始" in combined_f3) or ("NoModel" in combined_f3),
      detail=combined_f3[-400:])

# F4 opt-in 真 LLM（出网、一次真调用、约 30s）
if os.environ.get("TRIMUM_ACCEPT_E7_LLM") == "1":
    r_f4 = run_cli([PY, "-m", "trimum_core.cli", "exec", "--code",
                    "在当前目录建一个 hello.txt 写上 hi", "--dry-run", "--json"],
                   cwd=WORK)
    _f4 = r_f4.stdout + r_f4.stderr
    # 唯一红线：不许崩（未捕获异常 / Traceback）；也不许 rc=0 却没有真会话。
    check("F4 真 LLM 链路不是崩溃（无 Traceback）", "Traceback" not in _f4,
          detail=_f4[-400:])
    if r_f4.returncode == 0:
        check("F4 正向链路跑通（rc=0 且 JSON 含 session）",
              '"session_id"' in r_f4.stdout, detail=_f4[-400:])
    else:
        # rc≠0 在本仓有两种**都算合格**的如实失败（2026-09-29 实测：真模型对这个小任务
        # 给的是 `printf 'hi' > hello.txt` + 空锚点 edit ⇒ change_rejected，rc=1，
        # 但 stdio 里是一份完整的 ok:false 记录 —— 这与「没有模型」是两回事）：
        #   ① 起不来      —— stderr 是「编码会话无法开始（…）」（NoModelError）
        #   ② 跑过但失败  —— stdout 是 `{"session_id": …, "ok": false, …}`
        # 这两条都与「模型今天在不在线」解耦，永远可判；不许因为模型抽风就整脚本变红。
        no_model = "无法开始" in _f4
        ran_but_failed = '"session_id"' in r_f4.stdout and '"ok": false' in r_f4.stdout
        check("F4 rc≠0 只允许这两种如实失败：无法开始 / 会话跑过但改动被拒",
              no_model or ran_but_failed, detail=_f4[-400:])
else:
    print("F4 未跑（opt-in 未开）")

# ── 汇总 ───────────────────────────────────────────────────
print(f"== E7 验收：{len(PASS)} passed / {len(FAIL)} failed ==")
for label in FAIL:
    print(f"  FAILED: {label}")
print(f"artifacts: TRIMUM_HOME={HOME} work={WORK}"
      "（默认跑完即清；要留证据加 TRIMUM_ACCEPT_E7_KEEP=1）")
sys.exit(1 if FAIL else 0)
