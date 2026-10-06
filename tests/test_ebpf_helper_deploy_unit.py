"""`ebpf1` 部署件（systemd 单元模板 + 安装脚本）的静态不变量测。

只读文件：真施加（chgrp / chmod / systemctl / 起单元）一律本人 sudo 跑，不进测试。
背景（2026-10-06 真机实测）：单元的 capability 集里没有 `CAP_DAC_OVERRIDE` / `CAP_DAC_READ_SEARCH`
⇒ uid 0 也一样守文件权限位 ⇒ 必须带 `Group=<客户端组>`，否则 helper 连自己的代码都 import 不了。
"""
from __future__ import annotations

import grp
import os
import pwd
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
UNIT = REPO / "deploy" / "trimum-bpf-helper.service"
SETUP = REPO / "scripts" / "setup_ebpf_helper.sh"
MARKER = "# TRIMUM_UNIT_GROUP_PLACEHOLDER"

# 安装脚本的「客户端组」推导与 DAC 预检共用一个工具函数 `dac_readable`；它的判类逻辑是安全红线，
# 这里用 `TRIMUM_BPF_DEPLOY_ROOT` 指向**合成树**做行为测试（不需要 root，也不碰真的 /opt/trimum）。


def _unit_text() -> str:
    return UNIT.read_text(encoding="utf-8")


def _setup_text() -> str:
    return SETUP.read_text(encoding="utf-8")


def test_unit_group_marker_is_a_comment_line():
    """占位必须是**注释行**：模板本身仍是合法 unit（`systemd-analyze verify` 直接验不报错），
    由安装脚本把它替换成真的 `Group=<客户端组>`。"""
    lines = _unit_text().splitlines()
    assert MARKER in lines
    assert all(not ln.startswith("Group=") for ln in lines), "模板里不许出现真的 Group=（渲染件才有）"


def test_unit_explains_why_group_is_required():
    text = _unit_text()
    assert "CAP_DAC_OVERRIDE" in text and "CAP_DAC_READ_SEARCH" in text
    assert "/opt/trimum" in text and "RuntimeDirectory" in text


def test_unit_sets_xdg_config_home_because_protecthome_hides_root():
    """`ProtectHome=yes` 把 /root 挡掉 ⇒ uid 0 的默认配置路径 /root/.config/... 读不到，
    `Path.exists()` 还会因 EACCES 抛出（真机实测 crash-loop）⇒ 单元必须把配置目录指到保护之外。"""
    text = _unit_text()
    assert "ProtectHome=yes" in text
    xdg = [ln for ln in text.splitlines() if ln.startswith("Environment=XDG_CONFIG_HOME=")]
    assert len(xdg) == 1, "单元必须且只能给一条 Environment=XDG_CONFIG_HOME="
    value = xdg[0].split("=", 2)[2]
    assert value and not value.startswith(("/root", "/home")), value


def test_setup_script_renders_marker_and_fails_loud():
    text = _setup_text()
    assert MARKER in text
    assert "Group=${CLIENT_GROUP}" in text                      # 替换目标
    assert 'grep -qx "Group=${CLIENT_GROUP}"' in text           # 替换没生效就 exit 1（不许静默降级）


def test_setup_script_derives_client_group_with_override():
    text = _setup_text()
    assert "systemctl show trmd -p User --value" in text
    assert "TRIMUM_BPF_CLIENT_USER" in text and "TRIMUM_BPF_CLIENT_GROUP" in text


def test_setup_script_dac_preflight_runs_before_install():
    """装之前必须证明「helper 的身份真读得到自己的代码」，否则会装出一个 crash-loop 的单元。"""
    text = _setup_text()
    assert "dac_readable" in text and "dac_preflight" in text
    assert text.index('LAST_STEP="dac-preflight"') < text.index('install -m 0644 "$RENDERED"')


def test_committed_deploy_artifacts_have_no_personal_identity():
    """public 仓库：本机用户名/组名不许写进 unit 模板或安装脚本（组名按机器推导）。"""
    for p in (UNIT, SETUP):
        assert "guzhujushi" not in p.read_text(encoding="utf-8"), f"{p} 写死了本机用户名"


# ---- DAC 预检的判类逻辑（行为测试：合成树 + --self-check） --------------------------
#
# 注意树要建在**祖先段对 uid 0 可穿**的地方（/tmp 是 1777），不能落在 pytest 的 `tmp_path`
# （`/tmp/pytest-of-<user>` 是 0700：属主＝测试用户、组/other 全无，检查器会先卡在祖先段 —— 那是**正确**结论，
# 但测不到本单要测的那一层）。

def _fake_deploy_root():
    root = Path(tempfile.mkdtemp(prefix="trm-dac-", dir="/tmp"))
    return root

@pytest.fixture
def fake_deploy_root():
    """合成部署树**自己**（不用再套一层子目录：mkdtemp 默认 0700，会被检查器先卡在祖先段）。"""
    root = _fake_deploy_root()
    os.chmod(root, 0o755)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)

def _make_fake_deploy_tree(root: Path, mode: int) -> None:
    (root / "src" / "trimum_core").mkdir(parents=True)
    (root / "src" / "trimum_core" / "bpf_helper_main.py").write_text("# fake\n", encoding="utf-8")
    (root / "venv" / "bin").mkdir(parents=True)
    (root / "venv" / "bin" / "python").write_text("", encoding="utf-8")
    for d, _, files in os.walk(root):
        os.chmod(d, 0o755)
        for f in files:
            os.chmod(Path(d) / f, 0o644)
    os.chmod(root, mode)                       # 只把**顶层**调成要测的模式


def _self_check(root: Path) -> subprocess.CompletedProcess:
    me = pwd.getpwuid(os.getuid()).pw_name
    my_group = grp.getgrgid(os.stat(root).st_gid).gr_name
    env = dict(os.environ)
    env["TRIMUM_BPF_DEPLOY_ROOT"] = str(root)
    env["TRIMUM_BPF_CLIENT_USER"] = me
    env["TRIMUM_BPF_CLIENT_GROUP"] = my_group
    return subprocess.run(
        ["bash", str(SETUP), "--self-check"],
        capture_output=True, text=True, env=env, timeout=180, check=False,
    )


def _deploy_tree_item(out: str) -> str:
    return next(ln for ln in out.splitlines() if "部署树对 helper 可读" in ln)

def _combined(r: subprocess.CompletedProcess) -> str:
    """卡点明细走 stderr（脚本里是 `... >&2 || true`），判定行走 stdout —— 断言时合并看。"""
    return r.stdout + r.stderr


def test_dac_check_accepts_group_traversable_tree(fake_deploy_root):
    root = fake_deploy_root
    _make_fake_deploy_tree(root, 0o750)        # 组有 r-x（helper 走 g 位）
    r = _self_check(root)
    assert "[OK]" in _deploy_tree_item(r.stdout)
    assert r.returncode == 0


def test_dac_check_rejects_owner_only_tree_even_if_client_is_the_owner(fake_deploy_root):
    """红线：helper 是 **uid 0**；`/opt/trimum` 那种「属主＝客户端用户」的目录对它算 other 类。
    曾经把「属主 == 客户端用户」当成 owner 类 ⇒ 检查恒放行（真机 crash-loop 就是被这么漏掉的）。"""
    root = fake_deploy_root
    _make_fake_deploy_tree(root, 0o700)        # 属主＝客户端用户、组/other 全无
    r = _self_check(root)
    out = _combined(r)
    item = _deploy_tree_item(r.stdout)
    assert "[FAIL]" in item
    assert "该类无 x" in out
    assert f"卡点：{root}" in out             # 卡点必须落在树根（而不是某个祖先）⇒ DEPLOY_ROOT 覆盖生效
    assert r.returncode != 0


def test_dac_check_rejects_missing_group_match(fake_deploy_root):
    root = fake_deploy_root
    _make_fake_deploy_tree(root, 0o750)
    me = pwd.getpwuid(os.getuid()).pw_name
    env = dict(os.environ)
    env["TRIMUM_BPF_DEPLOY_ROOT"] = str(root)
    env["TRIMUM_BPF_CLIENT_USER"] = me
    env["TRIMUM_BPF_CLIENT_GROUP"] = "nogroup"   # 与合成树的属组不匹配 ⇒ other 类 ⇒ other 位 0
    r = subprocess.run(["bash", str(SETUP), "--self-check"], capture_output=True, text=True,
                       env=env, timeout=180, check=False)
    assert "[FAIL]" in _deploy_tree_item(r.stdout)
    assert f"卡点：{root}" in _combined(r)
    assert r.returncode != 0
