"""Gate tests for ``scripts/apply_ebpf1e.sh`` (the one-shot sudo runbook for the real eBPF loader).

Only the read-only modes are exercised here (``--print-config`` / dry-run / argument handling): the tests
never write to /etc, never call sudo and never touch the installed unit. The real ``--apply`` is run by the
owner with sudo (see docs/SANDBOX-PLAN.md "6.7" and TODO.md "ebpf1e").

The important regression this file guards: the real host had a hand-written
``/etc/trimum/config.yaml`` whose line ``bpf_helper_allowed_uids:[1000]`` is a YAML scanner error (missing
space after ':'), so the file was rejected, the allow-list stayed empty and the helper denied every peer.
The script must (a) keep such a file as a backup, (b) replace it, and (c) produce YAML that the helper's own
``allowed_uids()`` parser reads back as ``{uid}``.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

from trimum_core.bpf_helper import ALLOWED_UIDS_CONFIG_KEY, allowed_uids

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "apply_ebpf1e.sh"
_ENV_PREFIXES = ("TRIMUM_BPF_",)

# The exact broken content found on the real host (2026-10-08): parses as a scanner error.
BROKEN_CONFIG = "security:\nbpf_helper_allowed_uids:[1000]\n"


def _run(*args: str, etc: Path | None = None, backup: Path | None = None,
         env: dict[str, str] | None = None):
    full_env = {k: v for k, v in os.environ.items() if not k.startswith(_ENV_PREFIXES)}
    if etc is not None:
        full_env["TRIMUM_BPF_ETC_DIR"] = str(etc)
    if backup is not None:
        full_env["TRIMUM_BPF_BACKUP_ROOT"] = str(backup)
    if env:
        full_env.update(env)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True, text=True, env=full_env, cwd=str(REPO), timeout=120,
    )


def _kv(stdout: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" in line and not line.startswith((" ", "[")):
            key, _, val = line.partition("=")
            out[key.strip()] = val.strip()
    return out


def _rendered_yaml(stdout: str) -> dict:
    marker = "--- would write to "
    lines = stdout.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(marker))
    body = "\n".join(lines[start + 1:])
    return yaml.safe_load(body)


class _FakeConfig:
    """Minimal stand-in for ``trimum_core.config.Config`` (same ``get('a.b')`` semantics)."""

    def __init__(self, raw: dict):
        self.raw = raw

    def get(self, key_path: str, default=None):
        node = self.raw
        for part in key_path.split("."):
            if not isinstance(node, dict):
                return default
            node = node.get(part)
            if node is None:
                return default
        return node


def test_script_is_valid_bash():
    assert SCRIPT.is_file()
    proc = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr


def test_help_lists_every_mode():
    proc = _run("--help")
    assert proc.returncode == 0
    for flag in ("--print-config", "--apply", "--self-check", "--rollback"):
        assert flag in proc.stdout


def test_unknown_flag_exits_2():
    proc = _run("--nope")
    assert proc.returncode == 2
    assert "unknown argument" in proc.stderr


def test_uid_flag_needs_a_value():
    proc = _run("--uid")
    assert proc.returncode == 1
    assert "--uid" in proc.stderr


def test_print_config_renders_the_helper_key(tmp_path: Path):
    proc = _run("--print-config", "--uid", "1234", etc=tmp_path, backup=tmp_path)
    assert proc.returncode == 0, proc.stderr
    kv = _kv(proc.stdout)
    assert kv["allowed_uid"] == "1234"
    assert kv["config_path"] == str(tmp_path / "config.yaml")
    assert kv["existing_config"] == "absent"
    assert kv["sync_cmd"].endswith("scripts/sync_opt_tree.sh --from-home")
    data = _rendered_yaml(proc.stdout)
    assert data["security"]["bpf_helper_allowed_uids"] == [1234]
    assert allowed_uids(config=_FakeConfig(data)) == frozenset({1234})


def test_print_config_uses_the_helper_constant(tmp_path: Path):
    """The rendered key must be the one the helper actually reads (guards against a rename drift)."""
    proc = _run("--print-config", "--uid", "1000", etc=tmp_path, backup=tmp_path)
    section, _, key = ALLOWED_UIDS_CONFIG_KEY.partition(".")
    data = _rendered_yaml(proc.stdout)
    assert data[section][key] == [1000]
    assert SCRIPT.read_text(encoding="utf-8").count(ALLOWED_UIDS_CONFIG_KEY) >= 1


def test_print_config_uid_flag_beats_env(tmp_path: Path):
    proc = _run("--print-config", "--uid", "2222", etc=tmp_path, backup=tmp_path,
                env={"TRIMUM_BPF_ALLOWED_UID": "1111"})
    assert _kv(proc.stdout)["allowed_uid"] == "2222"
    assert _rendered_yaml(proc.stdout)["security"]["bpf_helper_allowed_uids"] == [2222]


def test_print_config_env_beats_derived_uid(tmp_path: Path):
    proc = _run("--print-config", etc=tmp_path, backup=tmp_path,
                env={"TRIMUM_BPF_ALLOWED_UID": "1111", "TRIMUM_BPF_CLIENT_USER": "nobody"})
    kv = _kv(proc.stdout)
    assert kv["client_user"] == "nobody"
    assert kv["allowed_uid"] == "1111"


def test_print_config_keeps_unrelated_keys(tmp_path: Path):
    (tmp_path / "config.yaml").write_text(
        "log_level: debug\nsecurity:\n  sandbox: true\n  bpf_alerts: /tmp/x.jsonl\n", encoding="utf-8")
    proc = _run("--print-config", "--uid", "1000", etc=tmp_path, backup=tmp_path)
    kv = _kv(proc.stdout)
    assert kv["existing_config"] == "ok"
    data = _rendered_yaml(proc.stdout)
    assert data["log_level"] == "debug"
    assert data["security"]["sandbox"] is True
    assert data["security"]["bpf_alerts"] == "/tmp/x.jsonl"
    assert data["security"]["bpf_helper_allowed_uids"] == [1000]


def test_print_config_flags_the_real_host_broken_file(tmp_path: Path):
    """Regression: the exact malformed file that silently kept the helper fail-closed."""
    (tmp_path / "config.yaml").write_text(BROKEN_CONFIG, encoding="utf-8")
    proc = _run("--print-config", "--uid", "1000", etc=tmp_path, backup=tmp_path)
    assert proc.returncode == 0, proc.stderr
    kv = _kv(proc.stdout)
    assert kv["existing_config"] == "broken"
    assert "not valid YAML" in kv["existing_config_note"]
    data = _rendered_yaml(proc.stdout)
    assert allowed_uids(config=_FakeConfig(data)) == frozenset({1000})


def test_print_config_handles_non_mapping_yaml(tmp_path: Path):
    (tmp_path / "config.yaml").write_text("- just\n- a list\n", encoding="utf-8")
    proc = _run("--print-config", "--uid", "1000", etc=tmp_path, backup=tmp_path)
    assert _kv(proc.stdout)["existing_config"] == "not-mapping"
    assert _rendered_yaml(proc.stdout)["security"]["bpf_helper_allowed_uids"] == [1000]


def test_dry_run_touches_nothing(tmp_path: Path):
    etc = tmp_path / "etc"
    etc.mkdir()
    (etc / "config.yaml").write_text(BROKEN_CONFIG, encoding="utf-8")
    backup = tmp_path / "backups"
    before = (etc / "config.yaml").read_bytes()
    proc = _run(etc=etc, backup=backup)
    assert proc.returncode == 0, proc.stderr
    assert "dry-run" in proc.stdout
    assert (etc / "config.yaml").read_bytes() == before
    assert not backup.exists(), "dry-run must not create the backup/log run dir"
    assert not (etc / ".config.yaml.new").exists()


def test_dry_run_prints_plan_and_shows_existing_state(tmp_path: Path):
    (tmp_path / "config.yaml").write_text(BROKEN_CONFIG, encoding="utf-8")
    proc = _run(etc=tmp_path, backup=tmp_path)
    assert "(existing: broken)" in proc.stdout
    assert "[1/4]" in proc.stdout and "[4/4]" in proc.stdout
    assert "self-check" in proc.stdout


@pytest.mark.skipif(os.geteuid() == 0, reason="root would actually apply")
def test_apply_requires_root(tmp_path: Path):
    proc = _run("--apply", etc=tmp_path, backup=tmp_path)
    assert proc.returncode == 1
    assert "needs root" in proc.stderr
    assert not (tmp_path / "config.yaml").exists()


def test_script_has_no_hardcoded_home_or_host_ip():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "/home/" not in text
    assert "100.115." not in text
    assert "guzhujushi" not in text


def test_render_is_idempotent(tmp_path: Path):
    """Two runs of the merge must produce byte-identical YAML (that is what ``cmp -s`` in step 1 relies on)."""
    (tmp_path / "config.yaml").write_text(BROKEN_CONFIG, encoding="utf-8")
    first = _rendered_yaml(_run("--print-config", "--uid", "1000", etc=tmp_path, backup=tmp_path).stdout)
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(first, sort_keys=False, default_flow_style=None), encoding="utf-8")
    proc = _run("--print-config", "--uid", "1000", etc=tmp_path, backup=tmp_path)
    assert _kv(proc.stdout)["existing_config"] == "ok"
    assert _rendered_yaml(proc.stdout) == first


# --------------------------------------------------------------------------------------
# --apply plumbing: exercised with stub wrapped-scripts + the TRIMUM_BPF_ALLOW_NONROOT
# escape hatch (the same idea as scripts/sync_opt_tree.sh's TRIMUM_ALLOW_NONROOT).
# No real sync, no clang, no systemd, no /etc write.
# --------------------------------------------------------------------------------------


def _stub_scripts(tmp_path: Path, *, sync_rc: int = 0, check_fails: int = 0, check_rc: int = 0):
    marker = tmp_path / "calls.txt"
    sync = tmp_path / "stub_sync.sh"
    sync.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "sync $*" >> "{marker}"\n'
        f"exit {sync_rc}\n",
        encoding="utf-8",
    )
    setup = tmp_path / "stub_setup.sh"
    setup.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "setup $*" >> "{marker}"\n'
        'case "$1" in\n'
        "  --apply) exit 0 ;;\n"
        f'  --self-check) printf "  \u5c0f\u7ed3\uff1aOK=4  FAIL={check_fails}  SKIP=1\\n"; exit {check_rc} ;;\n'
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    return marker, sync, setup


def _apply_env(sync: Path, setup: Path) -> dict:
    # Step 0 (kernel perf gate) is neutralised for the plumbing tests: the fake sysctl reports
    # paranoid=3, so the gate is "off", nothing is written and no real /proc or /etc path is touched.
    fake_paranoid = sync.parent / "paranoid"
    fake_paranoid.write_text("3\n", encoding="utf-8")
    return {
        "TRIMUM_BPF_SYNC_SH": str(sync),
        "TRIMUM_BPF_SETUP_SH": str(setup),
        "TRIMUM_BPF_ALLOW_NONROOT": "1",
        "TRIMUM_BPF_ALLOWED_UID": "1000",
        "TRIMUM_BPF_PARANOID_FILE": str(fake_paranoid),
        "TRIMUM_BPF_KERNEL_CONFIG": str(sync.parent / "kernel-config"),
        "TRIMUM_BPF_PERF_DROPIN": str(sync.parent / "perf-dropin.conf"),
        "TRIMUM_BPF_SYSCTL_BIN": "/bin/true",
    }


def _calls(marker: Path) -> list[str]:
    return marker.read_text(encoding="utf-8").splitlines() if marker.exists() else []


def test_apply_pipeline_runs_config_then_sync_then_install_then_self_check(tmp_path: Path):
    etc, backup = tmp_path / "etc", tmp_path / "backups"
    marker, sync, setup = _stub_scripts(tmp_path)
    proc = _run("--apply", etc=etc, backup=backup, env=_apply_env(sync, setup))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _calls(marker) == ["sync --from-home", "setup --apply", "setup --self-check"]
    data = yaml.safe_load((etc / "config.yaml").read_text(encoding="utf-8"))
    assert allowed_uids(config=_FakeConfig(data)) == frozenset({1000})
    assert "verdict: OK=4  FAIL=0  SKIP=1" in proc.stdout
    assert "== done ==" in proc.stdout
    logs = list(backup.glob("ebpf1e-*/ebpf1e.log"))
    assert len(logs) == 1, "the wrapped scripts' raw output must land in one run log"
    # the wrapped scripts' stdout is captured (that is the point of the log file), not dumped to the console
    assert "FAIL=0" in logs[0].read_text(encoding="utf-8", errors="replace")


def test_apply_stops_when_sync_fails(tmp_path: Path):
    etc, backup = tmp_path / "etc", tmp_path / "backups"
    marker, sync, setup = _stub_scripts(tmp_path, sync_rc=3)
    proc = _run("--apply", etc=etc, backup=backup, env=_apply_env(sync, setup))
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "sync_opt_tree.sh rc=3" in proc.stdout
    assert _calls(marker) == ["sync --from-home"], "install must not run after a failed sync"
    assert (etc / "config.yaml").exists(), "step 1 is idempotent and runs before step 2"


def test_apply_fails_when_self_check_reports_a_failure(tmp_path: Path):
    etc, backup = tmp_path / "etc", tmp_path / "backups"
    marker, sync, setup = _stub_scripts(tmp_path, check_fails=1, check_rc=1)
    proc = _run("--apply", etc=etc, backup=backup, env=_apply_env(sync, setup))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "verdict: OK=4  FAIL=1  SKIP=1" in proc.stdout
    assert "1 check(s) failed" in proc.stdout
    assert "== done ==" not in proc.stdout, "FAIL=0 is required for a green run"


def test_apply_skip_sync_does_not_call_the_sync_script(tmp_path: Path):
    etc, backup = tmp_path / "etc", tmp_path / "backups"
    marker, sync, setup = _stub_scripts(tmp_path)
    proc = _run("--apply", "--skip-sync", etc=etc, backup=backup, env=_apply_env(sync, setup))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "skipped (--skip-sync)" in proc.stdout
    assert _calls(marker) == ["setup --apply", "setup --self-check"]


def test_apply_backs_up_the_replaced_config(tmp_path: Path):
    etc, backup = tmp_path / "etc", tmp_path / "backups"
    etc.mkdir()
    (etc / "config.yaml").write_text(BROKEN_CONFIG, encoding="utf-8")
    marker, sync, setup = _stub_scripts(tmp_path)
    proc = _run("--apply", etc=etc, backup=backup, env=_apply_env(sync, setup))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    run_dirs = list(backup.glob("ebpf1e-*"))
    assert len(run_dirs) == 1
    assert (run_dirs[0] / "config.yaml").read_text(encoding="utf-8") == BROKEN_CONFIG
    assert (run_dirs[0] / "config.yaml.sha256").is_file()
    assert yaml.safe_load((etc / "config.yaml").read_text(encoding="utf-8"))["security"][
        "bpf_helper_allowed_uids"] == [1000]


def test_apply_second_run_is_a_noop_for_the_config(tmp_path: Path):
    etc, backup = tmp_path / "etc", tmp_path / "backups"
    marker, sync, setup = _stub_scripts(tmp_path)
    assert _run("--apply", etc=etc, backup=backup, env=_apply_env(sync, setup)).returncode == 0
    second = _run("--apply", etc=etc, backup=backup, env=_apply_env(sync, setup))
    assert second.returncode == 0, second.stdout + second.stderr
    assert "already up to date (byte-identical)" in second.stdout


def test_apply_purges_stale_bytecode_in_the_deploy_tree(tmp_path: Path):
    """`--apply` 必须在同步后清掉部署树的 `__pycache__`。

    CPython 用「源文件 mtime 的**整秒**」校验 .pyc：若文件被复制/改写落在同一秒内，旧字节码会被静默沿用
    （2026-10-08 本地实测踩到：sed 改一行再还原，两次 mtime 同秒 ⇒ 一直在跑缓存里那份旧代码）。
    helper 是从部署树 import 的，所以这一步不能省。
    """
    etc, backup = tmp_path / "etc", tmp_path / "backups"
    deploy = tmp_path / "deploy"
    stale = deploy / "src" / "trimum_core" / "__pycache__"
    stale.mkdir(parents=True)
    (stale / "bpf_helper.cpython-312.pyc").write_bytes(b"stale")
    marker, sync, setup = _stub_scripts(tmp_path)
    env = dict(_apply_env(sync, setup))
    env["TRIMUM_BPF_DEPLOY_ROOT"] = str(deploy)
    proc = _run("--apply", etc=etc, backup=backup, env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "purged 1 stale __pycache__" in proc.stdout
    assert not stale.exists()


# --------------------------------------------------------------------------------------
# Step 0: the kernel perf gate (Ubuntu CONFIG_SECURITY_PERF_EVENTS_RESTRICT)
# --------------------------------------------------------------------------------------

def _perf_gate_env(tmp_path: Path, sync: Path, setup: Path, *, paranoid: str, config: str,
                   dropin: Path, sysctl_script: Path | None = None) -> dict:
    env = dict(_apply_env(sync, setup))
    # write the fakes *after* _apply_env (it seeds the same paranoid path with "3" for the other tests)
    paranoid_file = tmp_path / "paranoid"
    paranoid_file.write_text(paranoid + "\n", encoding="utf-8")
    config_file = tmp_path / "kernel-config"
    config_file.write_text(config, encoding="utf-8")
    env.update({
        "TRIMUM_BPF_PARANOID_FILE": str(paranoid_file),
        "TRIMUM_BPF_KERNEL_CONFIG": str(config_file),
        "TRIMUM_BPF_PERF_DROPIN": str(dropin),
    })
    if sysctl_script is not None:
        env["TRIMUM_BPF_SYSCTL_BIN"] = str(sysctl_script)
    return env


def test_step0_lowers_perf_event_paranoid_instead_of_granting_cap_sys_admin(tmp_path: Path):
    """Ubuntu's CONFIG_SECURITY_PERF_EVENTS_RESTRICT makes perf_event_open(2) CAP_SYS_ADMIN-only while
    kernel.perf_event_paranoid >= 4, so libbpf's tracepoint attach returns EACCES and the helper's
    CAP_BPF+CAP_PERFMON is not enough (2026-10-08 real-host failure). Step 0 must drop the sysctl via a
    drop-in file -- never touch the unit's capability set."""
    etc, backup = tmp_path / "etc", tmp_path / "backups"
    marker, sync, setup = _stub_scripts(tmp_path)
    dropin = tmp_path / "sysctl.d" / "60-trimum-perf.conf"
    fake_sysctl = tmp_path / "fake-sysctl.sh"
    fake_sysctl.write_text(
        '#!/usr/bin/env bash\nprintf "3\\n" > "$TRIMUM_BPF_PARANOID_FILE"\n', encoding="utf-8")
    fake_sysctl.chmod(0o755)
    env = _perf_gate_env(tmp_path, sync, setup, paranoid="4",
                         config="CONFIG_SECURITY_PERF_EVENTS_RESTRICT=y\n",
                         dropin=dropin, sysctl_script=fake_sysctl)
    proc = _run("--apply", etc=etc, backup=backup, env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "[0/4]" in proc.stdout
    body = dropin.read_text(encoding="utf-8")
    assert body.strip().endswith("kernel.perf_event_paranoid=3")
    assert "CAP_SYS_ADMIN" in body, "the drop-in must explain *why* the sysctl is lowered"
    assert (tmp_path / "paranoid").read_text(encoding="utf-8").strip() == "3"
    assert _calls(marker) == ["sync --from-home", "setup --apply", "setup --self-check"]


def test_step0_is_a_noop_when_the_kernel_allows_perf_event_open(tmp_path: Path):
    etc, backup = tmp_path / "etc", tmp_path / "backups"
    _marker, sync, setup = _stub_scripts(tmp_path)
    dropin = tmp_path / "sysctl.d" / "60-trimum-perf.conf"
    env = _perf_gate_env(tmp_path, sync, setup, paranoid="4",
                         config="# no CONFIG_SECURITY_PERF_EVENTS_RESTRICT in this kernel\n",
                         dropin=dropin)
    proc = _run("--apply", etc=etc, backup=backup, env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not dropin.exists()
    assert (tmp_path / "paranoid").read_text(encoding="utf-8").strip() == "4"


def test_self_check_failure_points_at_the_perf_gate(tmp_path: Path):
    """The 18:24 run failed with exactly one check and no usable hint; the hint must be printed when the
    gate is still active (that is the state a bare `--self-check` sees)."""
    backup = tmp_path / "backups"
    _marker, sync, setup = _stub_scripts(tmp_path, check_fails=1, check_rc=1)
    dropin = tmp_path / "sysctl.d" / "60-trimum-perf.conf"
    env = _perf_gate_env(tmp_path, sync, setup, paranoid="4",
                         config="CONFIG_SECURITY_PERF_EVENTS_RESTRICT=y\n", dropin=dropin)
    proc = _run("--self-check", backup=backup, env=env)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "CAP_SYS_ADMIN-only" in proc.stdout
    assert str(dropin) in proc.stdout, "the hint must name the fix (step 0's drop-in)"
