"""E4 真机验收（无需 sudo）：三个导入器 + 六条红线。

跑法（真机、以 guzhujushi 身份）：

    cd /home/guzhujushi/trimum && .venv/bin/python /tmp/accept_e4.py

用临时 ``TRIMUM_HOME`` 收下所有导入产物（跑完留在 /tmp，不碰 ~/.trimum），
并用一个哨兵文件 ``/tmp/TRM-E4-MUST-NOT-EXIST`` 盯着红线「导入不执行任何东西」：
每一条导入命令里都写着删除它，验收全程它都不该出现。
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

APP = Path(os.environ.get("TRIMUM_APP_DIR", "/home/guzhujushi/trimum"))


def _interpreter() -> Path:
    """开发树是 `.venv/`，部署树 `/opt/trimum` 是 `venv/`。"""
    for name in (".venv", "venv"):
        candidate = APP / name / "bin" / "python"
        if candidate.exists():
            return candidate
    return Path(sys.executable)  # 兜底：用当前解释器


REPO = APP
PY = str(_interpreter())
HOME = Path(tempfile.mkdtemp(prefix="e4home-"))
WORK = Path(tempfile.mkdtemp(prefix="e4work-"))
MARKER = Path("/tmp/TRM-E4-MUST-NOT-EXIST")
env = dict(os.environ, TRIMUM_HOME=str(HOME), PYTHONIOENCODING="utf-8")

PASS: list[str] = []
FAIL: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    (PASS if condition else FAIL).append(label)
    mark = "ok  " if condition else "FAIL"
    print(f"[{mark}] {label}" + (f"  -- {detail}" if detail and not condition else ""))
    sys.stdout.flush()


def trm(*args: str, timeout: float = 180.0):
    proc = subprocess.run(
        [PY, "-m", "trimum_core.cli", *args],
        cwd=str(REPO), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    out = proc.stdout[proc.stdout.find("{"):] if "{" in proc.stdout else proc.stdout
    return proc.returncode, out, proc.stderr


def payload(*args: str, timeout: float = 180.0) -> tuple[int, dict, str]:
    rc, out, err = trm(*args, timeout=timeout)
    try:
        return rc, json.loads(out), err
    except json.JSONDecodeError:
        return rc, {}, f"{err}\n{out[:400]}"


print(f"host python: {PY}")
print(f"TRIMUM_HOME: {HOME}")
print(f"work dir   : {WORK}")
print()

# ── A. 通用 CLI 适配器 ────────────────────────────────────────────────
rc, data, err = payload("tool", "import-cli", "git", "--name", "gitshim", "--subcommands", "3", "--yes", "--json")
check("A1 import-cli git 成功", rc == 0 and data.get("written"), err)
entry = data.get("entry") or {}
check("A2 默认 enabled=false（注册 != 授权）", entry.get("enabled") is False, str(entry))
check("A3 trust=third-party", entry.get("trust") == "third-party")
check("A4 风险有分级理由", bool(entry.get("risk_reasons")), str(entry.get("risk_reasons")))
check(
    "A5 探测到子命令",
    bool((data.get("binary") or {}).get("verified_subcommands")),
    str((data.get("binary") or {}).get("subcommands")),
)
check("A6 落了 manifest + main.py", len(data.get("written") or []) == 2, str(data.get("written")))

manifest_path = HOME / "tools" / "gitshim" / "tool.json5"
sys.path.insert(0, str(REPO / "src"))
from trimum_core.tool_file_loader import load_manifest  # noqa: E402

manifest = load_manifest(manifest_path) or {}
check("A7 manifest 能被解析（JSON5 注释不挡）", manifest.get("name") == "gitshim", str(manifest)[:200])
check("A8 免确认旗标没进白名单", "--force" not in (manifest.get("allowed_flags") or []))

# ── B/C/D. list / enable / disable ────────────────────────────────────
rc, data, err = payload("tool", "list", "--json")
names = [item["name"] for item in (data.get("tools") or [])]
check("B1 未启用时不在注册表里", "gitshim" not in names, str(names))

rc, data, err = payload("tool", "list", "--all", "--json")
rows = {item["name"]: item for item in (data.get("tools") or [])}
check("B2 list --all 能看到它（disabled）", rows.get("gitshim", {}).get("enabled") is False, str(rows.get("gitshim")))

rc, data, err = payload("tool", "enable", "gitshim", "--json")
check("C1 enable 成功", rc == 0 and data.get("enabled") is True, err)
rc, data, err = payload("tool", "list", "--json")
names = [item["name"] for item in (data.get("tools") or [])]
check("C2 启用后进注册表", "gitshim" in names, str(names))

rc, data, err = payload("tool", "disable", "gitshim", "--json")
check("D1 disable 成功", rc == 0 and data.get("enabled") is False, err)
rc, data, err = payload("tool", "list", "--json")
names = [item["name"] for item in (data.get("tools") or [])]
check("D2 关掉后不在注册表里", "gitshim" not in names, str(names))
check("D3 disable 不删文件", manifest_path.is_file())


# ── E. 运行时白名单（generic_executor 自己再兜一层）──────────────────
from trimum_core.cli_adapter import generic_executor  # noqa: E402

binding = manifest.get("binding") or {}


async def run_binding(args):
    return await generic_executor(binding, {"args": args})


bad = asyncio.run(run_binding(["--definitely-not-a-flag"]))
check("E1 白名单外的旗标被拒（还没 spawn）", bad.get("exit_code") == 2, str(bad))
check("E2 拒绝理由可读", "flag not allowed" in str(bad.get("error")), str(bad.get("error")))

unknown = asyncio.run(run_binding(["definitely-not-a-subcommand"]))
check("E3 未探测到的子命令被拒", unknown.get("exit_code") == 2, str(unknown))

if "--version" in (binding.get("allowed_flags") or []):
    good = asyncio.run(run_binding(["--version"]))
    check("E4 白名单内的旗标真跑通", good.get("exit_code") == 0 and "git version" in str(good.get("output")), str(good)[:200])
else:
    check("E4 白名单内的旗标真跑通", False, "--version 不在白名单里")

# ── F. workflow 目录导入 ──────────────────────────────────────────────
catalog_dir = WORK / "catalogs"
catalog_dir.mkdir(parents=True, exist_ok=True)
catalog_dir.joinpath("e4-marker.yaml").write_text(
    "name: E4 marker\n"
    "description: 导入不应该执行任何命令\n"
    "risk: low\n"
    "command: rm -f /tmp/TRM-E4-MUST-NOT-EXIST\n",
    encoding="utf-8",
)

rc, data, err = payload("workflow", "import", str(catalog_dir), "--dry-run", "--json")
rows = {item.get("id"): item for item in (data.get("workflows") or [])}
row = rows.get("e4-marker") or {}
check("F1 dry-run 通过并给出条目", rc == 0 and row.get("problems") == [], str(row))
check("F2 dry-run 不落盘", not (HOME / "workflows").exists())
check("F3 声明的 risk=low 被命令里的 rm 顶成 high", (row.get("entry") or {}).get("risk") == "high", str(row.get("entry")))
check("F4 理由里点名了触发词", any("rm" in r for r in (row.get("entry") or {}).get("risk_reasons") or []), str(row.get("entry")))
check("F5 声明低于探测时有警告", any("低于" in w for w in row.get("warnings") or []), str(row.get("warnings")))
check("F6 红线：导入没有执行命令", not MARKER.exists())

rc, data, err = payload("workflow", "import", str(catalog_dir), "--yes", "--json")
check("F7 真导入写盘", rc == 0 and len(data.get("written") or []) == 1, err)
rc, data, err = payload("workflow", "list", "--json")
ids = [item["id"] for item in (data.get("workflows") or [])]
check("F8 workflow list 能看到", "e4-marker" in ids, str(ids))
check("F9 仍然没有执行任何命令", not MARKER.exists())

rc, _, err = payload("workflow", "import", str(catalog_dir), "--yes", "--json")
check("F10 重复导入被拒（没有 --force）", rc == 1 and "已存在" in err, err)


# ── G. skill 导入（本地目录）──────────────────────────────────────────
skill_src = WORK / "skills-src"
skill_dir = skill_src / "e4-skill"
skill_dir.mkdir(parents=True, exist_ok=True)
skill_md = "---\nname: e4-skill\ndescription: E4 acceptance skill.\n---\n\n# E4\n"
skill_dir.joinpath("SKILL.md").write_text(skill_md, encoding="utf-8")
skill_dir.joinpath("helper.py").write_text("print('hi')\n", encoding="utf-8")

rc, data, err = payload("skill", "import", str(skill_src), "--dry-run", "--json")
rows = {item.get("name"): item for item in (data.get("skills") or [])}
row = rows.get("e4-skill") or {}
check("G1 dry-run 校验通过", rc == 0 and row.get("problems") == [], str(row))
check("G2 dry-run 不落盘", not (HOME / "skills").exists())

rc, data, err = payload("skill", "import", str(skill_src), "--yes", "--json")
installed = data.get("installed") or []
check("G3 真导入写盘", rc == 0 and len(installed) == 1, err)
copied = HOME / "skills" / "e4-skill" / "SKILL.md"
check("G4 SKILL.md 逐字节一致", copied.is_file() and copied.read_text(encoding="utf-8") == skill_md)
check("G5 附件一起搬", (HOME / "skills" / "e4-skill" / "helper.py").is_file())

rc, data, err = payload("skill", "list", "--json")
names = [item["name"] for item in (data.get("skills") or [])]
check("G6 skill list 能看到（默认根一致）", "e4-skill" in names, str(names))
check("G7 导入没有执行技能里的东西", not MARKER.exists())

rc, _, err = payload("skill", "import", str(skill_src), "--yes", "--json")
check("G8 重复导入被拒", rc == 1 and "已存在" in err, err)

# ── H. skill 导入（真 git clone）──────────────────────────────────────
repo = WORK / "upstream"
(repo / "skills" / "e4-git-skill").mkdir(parents=True, exist_ok=True)
(repo / "skills" / "e4-git-skill" / "SKILL.md").write_text(
    "---\nname: e4-git-skill\ndescription: From a git repo.\n---\n\nBody\n", encoding="utf-8"
)
for cmd in (
    ["git", "init", "-q", str(repo)],
    ["git", "-C", str(repo), "add", "-A"],
    ["git", "-C", str(repo), "-c", "user.email=e4@example.invalid", "-c", "user.name=e4", "commit", "-q", "-m", "init"],
):
    subprocess.run(cmd, check=True, capture_output=True)
bare = WORK / "upstream.git"
repo.rename(bare)

rc, data, err = payload("skill", "import", str(bare), "--yes", "--json")
check("H1 git 源走 clone 并导入", rc == 0 and data.get("origin") == "git", f"{err} {data.get('origin')}")
check("H2 一层嵌套布局也能找到技能", [item["name"] for item in data.get("skills") or []] == ["e4-git-skill"], str(data.get("skills")))
leftovers = list(Path(tempfile.gettempdir()).glob("trm-skill-import-*"))
check("H3 克隆的临时目录没留下", not leftovers, str(leftovers))

# ── I. 全局 ───────────────────────────────────────────────────────────
rc, out, err = trm("commands", "--check")
check("I1 trm commands --check 无问题", rc == 0 and "no problems" in (out + err), (out + err)[-200:])
rc, out, err = trm("--version")
check("I2 trm --version 可用", rc == 0, (out + err)[-120:])
check("I3 整轮验收没有执行过导入物", not MARKER.exists())

print()
print(f"== E4 真机验收：{len(PASS)} passed / {len(FAIL)} failed ==")
for item in FAIL:
    print(f"  FAILED: {item}")
print(f"artifacts: TRIMUM_HOME={HOME} work={WORK}")
sys.exit(1 if FAIL else 0)
