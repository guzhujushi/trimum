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


def _bash_function(name: str) -> str:
    """把安装脚本里的一个函数原样抠出来（用于在隔离环境里跑它的参数契约）。"""
    lines = _setup_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{name}()"))
    body: list[str] = []
    for line in lines[start:]:
        body.append(line)
        if line == "}":
            break
    assert body[-1] == "}", f"没找到 {name}() 的结尾"
    return "\n".join(body)


def test_send_priv_as_tolerates_the_optional_program_argument(tmp_path: Path):
    """`send_priv_as <user> <verb>`（不带 program）不许在 `set -u` 下因裸写 `$3` 崩掉。

    回归（2026-10-08 真机 `--apply` 冒烟失败、自动回滚的真因）：`$3` 未绑定 ⇒ bash 报
    「未绑定的变量」并**整条 runuser 命令都不执行** ⇒ 客户端拿到空应答 ⇒ 冒烟判 FAIL。
    脚本本身没坏，命令根本没跑 —— 所以这里用假 `runuser` 直接验「argv 里一定带上空 program 位」。
    """
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    record = tmp_path / "argv.txt"
    fake_runuser = fake_bin / "runuser"
    fake_runuser.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$@" > "$FAKE_RUNUSER_RECORD"\ncat > /dev/null\n',
        encoding="utf-8",
    )
    fake_runuser.chmod(0o755)
    script = ("set -u\n" + _bash_function("send_priv_as")
              + "\nsend_priv_as guzhujushi bpf.stats\n")
    env = dict(os.environ)
    env.update({
        "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
        "FAKE_RUNUSER_RECORD": str(record),
        "VENV_PY": "/usr/bin/python3",
        "SOCK": "/run/trimum/priv.sock",
    })
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                          env=env, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert "unbound variable" not in proc.stderr, proc.stderr
    assert record.read_text(encoding="utf-8").splitlines() == [
        "-u", "guzhujushi", "--", "/usr/bin/python3", "-", "bpf.stats", "",
        "/run/trimum/priv.sock",
    ]


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


def test_unit_allows_the_bpf_syscalls_it_exists_for():
    """2026-10-08（ebpf1e）实测：systemd 的 `@system-service` **不含** `bpf`（在 `@privileged` 里），
    也不含 `perf_event_open`（在 `@debug` 里）——少了它们，seccomp 会把 loader 的加载判 EPERM。"""
    filters = [ln for ln in _unit_text().splitlines() if ln.startswith("SystemCallFilter=")]
    assert len(filters) == 1, filters
    value = filters[0].split("=", 1)[1]
    assert "@system-service" in value
    for syscall in ("bpf", "perf_event_open"):
        assert syscall in value.split(), "%s 必须在 SystemCallFilter 里" % syscall
    assert "LimitMEMLOCK=infinity" in _unit_text()


def test_setup_script_builds_and_installs_the_objects():
    """产物只放源码在仓库（`.o` 是构建产物）⇒ `--apply` 必须现场 clang 构建 + 装 0444 + 写清单。"""
    text = _setup_text()
    assert "build_bpf.sh" in text
    assert "--manifest /etc/trimum/bpf-manifest.txt" in text
    assert 'chmod 0444 "${DEPLOY_ROOT}"/bpf/*.bpf.o' in text
    # 构建在装单元之前，构建失败要早退（不许装出一个没有产物的单元）
    assert text.index("build_bpf.sh") < text.index('install -m 0644 "$RENDERED"')


def test_setup_script_restarts_the_unit_so_new_code_takes_effect():
    """`enable --now` 对**已在跑**的单元是空操作：不 restart 就还是旧代码 / 旧产物。"""
    text = _setup_text()
    assert 'systemctl restart "$UNIT"' in text
    assert text.index('systemctl enable --now "$UNIT"') < text.index('systemctl restart "$UNIT"')


def test_setup_script_self_check_checks_objects_and_end_to_end_load():
    text = _setup_text()
    assert "eBPF 产物与清单一致" in text
    assert "端到端 bpf.load bpf_guard 成功" in text
    assert 'send_priv_as "$CLIENT_USER" bpf.load bpf_guard' in text


def test_build_bpf_script_is_ascii_only_and_has_no_personal_identity():
    """构建脚本要在真机文字控制台能看 ⇒ 输出全 ASCII；public 仓库不写本机身份。"""
    build = REPO / "scripts" / "build_bpf.sh"
    assert build.exists(), "缺 scripts/build_bpf.sh"
    text = build.read_text(encoding="utf-8")
    assert not [ch for ch in text if ord(ch) > 127], "build_bpf.sh 里有非 ASCII 字符"
    assert "guzhujushi" not in text


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
def test_perf_gate_hint_explains_the_perf_event_open_denial(tmp_path: Path):
    """2026-10-08 真机定案：端到端 `bpf.load` 的失败来自**内核策略**，不是 seccomp/capability 配错。

    Ubuntu 内核带 `CONFIG_SECURITY_PERF_EVENTS_RESTRICT=y` ⇒ `kernel.perf_event_paranoid >= 4` 时
    libbpf 挂 tracepoint 用的 `perf_event_open(2)` 强制 CAP_SYS_ADMIN，而 helper 按设计只有
    `CAP_BPF+CAP_PERFMON` ⇒ EACCES / "Permission denied"。自检要能自己说出这条，而且必须是
    **ASCII**（真机控制台没有中文字形，apply_ebpf1e.sh 还会把非 ASCII 字节换成 '?'）。
    """
    hint = _bash_function("perf_gate_hint")
    paranoid = tmp_path / "paranoid"
    config = tmp_path / "kernel-config"

    def run(paranoid_value: str, config_text: str) -> str:
        paranoid.write_text(paranoid_value + "\n", encoding="utf-8")
        config.write_text(config_text, encoding="utf-8")
        env = dict(os.environ)
        env.update({"TRIMUM_BPF_PARANOID_FILE": str(paranoid),
                    "TRIMUM_BPF_KERNEL_CONFIG": str(config)})
        proc = subprocess.run(["bash", "-c", hint + "\nperf_gate_hint\n"], capture_output=True,
                              text=True, env=env, timeout=60)
        assert proc.returncode == 0, proc.stderr
        return proc.stdout

    on = run("4", "CONFIG_SECURITY_PERF_EVENTS_RESTRICT=y\n")
    assert "CAP_SYS_ADMIN" in on and "CAP_BPF+CAP_PERFMON" in on
    assert "apply_ebpf1e.sh" in on and "perf_event_paranoid<=3" in on
    assert on.isascii()
    assert run("3", "CONFIG_SECURITY_PERF_EVENTS_RESTRICT=y\n") == ""
    assert run("4", "# CONFIG_SECURITY_PERF_EVENTS_RESTRICT is not set\n") == ""
