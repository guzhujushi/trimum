"""S4 子 Agent 资源边界（``sandbox_limits``）用例。

对照 S4 交付口径：纯计算（**不起子进程、不碰 systemd**）、
`unsupported` 是如实降级不是失败、`MemoryMax` / `MemorySwapMax` 成对、
`-p` 顺序固定（不许字典序）。
"""

from __future__ import annotations

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from trimum_core import sandbox_limits as sl  # noqa: E402


class TestLimits:
    def test_defaults(self):
        limits = sl.Limits()
        assert limits.memory_max_bytes == 1 << 30
        assert limits.memory_swap_max_bytes == 0
        assert limits.cpu_quota_percent == 100
        assert limits.tasks_max == 128
        assert limits.no_new_privileges is True

    def test_no_syscall_filter_on_unit(self):
        """单元上不许有第二套 syscall 口径（会打死单元内的 Layer K 施加 ⇒ SIGSYS 31）。"""
        assert not hasattr(sl.Limits(), "system_call_filter")
        assert all("SystemCallFilter" not in p for p in sl.properties(sl.Limits()))

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"memory_max_bytes": 0},
            {"memory_max_bytes": -1 << 20},
            {"memory_swap_max_bytes": -1},
            {"cpu_quota_percent": 0},
            {"cpu_quota_percent": -5},
            {"tasks_max": 0},
            {"tasks_max": -1},
        ],
    )
    def test_invalid_limits_raise(self, kwargs):
        with pytest.raises(ValueError) as excinfo:
            sl.Limits(**kwargs)
        field = next(iter(kwargs))
        assert field in str(excinfo.value)

    def test_zero_or_negative_message_names_field(self):
        for kwargs in ({"memory_max_bytes": 0}, {"cpu_quota_percent": 0}, {"tasks_max": 0}):
            with pytest.raises(ValueError) as excinfo:
                sl.Limits(**kwargs)
            assert next(iter(kwargs)) in str(excinfo.value)


class TestProperties:
    def test_default_order_and_values(self):
        assert sl.properties(sl.Limits()) == (
            "MemoryMax=1073741824",
            "MemorySwapMax=0",
            "CPUQuota=100%",
            "TasksMax=128",
            "NoNewPrivileges=yes",
        )

    def test_non_default_keeps_fixed_order(self):
        """非默认值下顺序仍是 MemoryMax → MemorySwapMax → CPUQuota → TasksMax → …。

        字典序会把 CPUQuota 排到最前，这条能抓出被改成排序的实现。
        """
        limits = sl.Limits(cpu_quota_percent=25, memory_max_bytes=64 << 20,
                           tasks_max=16, no_new_privileges=False)
        props = sl.properties(limits)
        assert props[0] == "MemoryMax=67108864"
        assert props[1] == "MemorySwapMax=0"
        assert props[2] == "CPUQuota=25%"
        assert props[3] == "TasksMax=16"
        assert props[4] == "NoNewPrivileges=no"
        assert len(props) == 5

    def test_memory_pair_altogether(self):
        props = sl.properties(sl.Limits(memory_swap_max_bytes=1 << 20))
        assert "MemoryMax=" in props[0]
        assert "MemorySwapMax=" in props[1], "MemoryMax 与 MemorySwapMax 必须成对出现"


class TestPlanUnit:
    """``plan_unit()`` 与 ``build_command()`` 的分支口径必须一致（接线方靠它对表）。"""

    @pytest.mark.parametrize("agent_name", ["coder", "worker", "anon"])
    def test_matches_build_command(self, agent_name):
        for systemd_ok in (True, False):
            state, unit = sl.plan_unit(agent_name, systemd_ok)
            cmd = sl.build_command(["/bin/true"], agent_name, systemd_ok=systemd_ok)
            assert (state, unit) == (cmd.state, cmd.unit or "")
            expected = (
                (sl.STATE_SYSTEMD, sl.unit_name(agent_name))
                if systemd_ok
                else (sl.STATE_UNSUPPORTED, "")
            )
            assert (state, unit) == expected

    def test_explicit_unit_used_verbatim(self):
        """显式 `unit=` 必须原样进 `--unit=`（终止流程先拿单元名、后拼 argv）。"""
        cmd = sl.build_command(
            ["true"], "x", systemd_ok=True, unit="trimum-agent-custom.service",
        )
        assert cmd.unit == "trimum-agent-custom.service"
        assert "--unit=trimum-agent-custom.service" in cmd.argv
        assert "--unit=trimum-agent-x.service" not in cmd.argv


class TestUnitName:
    def test_plain(self):
        assert sl.unit_name("coder") == "trimum-agent-coder.service"

    def test_space_chinese_slash(self):
        for name in ("a b", "中文名字", "a/b"):
            unit = sl.unit_name(name)
            assert re.fullmatch(r"[A-Za-z0-9:_.-]+", unit), unit
            assert len(unit) <= sl.MAX_UNIT_LENGTH

    def test_overlong_truncated(self):
        unit = sl.unit_name("x" * 300)
        assert re.fullmatch(r"[A-Za-z0-9:_.-]+", unit)
        assert len(unit) <= sl.MAX_UNIT_LENGTH
        assert unit.startswith(sl.UNIT_PREFIX) and unit.endswith(".service")

    def test_empty_and_blank(self):
        assert sl.unit_name("") == "trimum-agent-anon.service"
        assert sl.unit_name("///") == "trimum-agent----.service"


class TestBuildCommand:
    def test_systemd_path_shape(self):
        cmd = sl.build_command(["/bin/bash", "-c", "echo hi"], "ctl",
                               limits=sl.Limits(cpu_quota_percent=25, memory_max_bytes=64 << 20),
                               systemd_ok=True)
        assert cmd.state == sl.STATE_SYSTEMD
        assert cmd.unit == "trimum-agent-ctl.service"
        assert cmd.argv[:7] == (
            "systemd-run", "--user", "--quiet", "--wait", "--pipe", "--collect",
            "--unit=trimum-agent-ctl.service",
        )
        props = sl.properties(sl.Limits(cpu_quota_percent=25, memory_max_bytes=64 << 20))
        middle = tuple(p for prop in props for p in ("-p", prop))
        assert cmd.argv[7:7 + len(middle)] == middle
        assert cmd.argv[7 + len(middle)] == "--"
        assert list(cmd.argv[cmd.argv.index("--") + 1 :]) == ["/bin/bash", "-c", "echo hi"]

    def test_systemd_path_order_with_non_default_limits(self):
        cmd = sl.build_command(["true"], "x", systemd_ok=True,
                               limits=sl.Limits(cpu_quota_percent=25, memory_max_bytes=64 << 20))
        dash_p = [i for i, a in enumerate(cmd.argv) if a == "-p"]
        values = [cmd.argv[i + 1] for i in dash_p]
        assert values == [
            "MemoryMax=67108864",
            "MemorySwapMax=0",
            "CPUQuota=25%",
            "TasksMax=128",
            "NoNewPrivileges=yes",
        ], "顺序固定：MemoryMax → MemorySwapMax → CPUQuota → TasksMax → NoNewPrivileges"

    def test_degraded_path_keeps_argv_verbatim(self):
        orig = ["/bin/bash", "-c", "echo degraded", "arg with space"]
        cmd = sl.build_command(orig, "x", limits=sl.Limits(cpu_quota_percent=25),
                               systemd_ok=False)
        assert cmd.state == sl.STATE_UNSUPPORTED
        assert cmd.unit is None
        assert list(cmd.argv) == orig, "降级必须逐项原样、一个 -p 都不加"

    def test_empty_argv_raises(self):
        with pytest.raises(ValueError):
            sl.build_command([], systemd_ok=True)

    def test_original_argv_not_mutated(self):
        orig = ["/bin/bash", "-c", "echo hi"]
        sl.build_command(orig, "ctl", systemd_ok=True)
        assert orig == ["/bin/bash", "-c", "echo hi"]

    def test_default_args_byte_identical(self):
        """不传 env/workdir ⇒ argv 与旧口径逐字节一致（现有期望值）。"""
        cmd = sl.build_command(["true"], "x", systemd_ok=True)
        assert cmd.argv == (
            "systemd-run", "--user", "--quiet", "--wait", "--pipe", "--collect",
            "--unit=trimum-agent-x.service",
            *tuple(p for prop in sl.properties(sl.Limits()) for p in ("-p", prop)),
            "--", "true",
        )

    def test_env_workdir_emitted_in_fixed_order(self):
        cmd = sl.build_command(
            ["true"], "x", systemd_ok=True,
            env={"TRIMUM_B": "2", "TRIMUM_A": "1", "TRIMUM_AGENT_ID": "abc"},
            workdir="/tmp/agentdir",
        )
        argv = cmd.argv
        assert "--working-directory=/tmp/agentdir" in argv
        # 各 --setenv 按 key 升序，且只出现 TRIMUM_ 前缀键
        setenvs = [a for a in argv if a.startswith("--setenv=")]
        assert setenvs == [
            "--setenv=TRIMUM_A=1",
            "--setenv=TRIMUM_AGENT_ID=abc",
            "--setenv=TRIMUM_B=2",
        ]
        # 顺序固定：unit → working-directory → setenv 们 → -p → --
        unit_i = argv.index("--unit=trimum-agent-x.service")
        wd_i = argv.index("--working-directory=/tmp/agentdir")
        first_setenv_i = argv.index("--setenv=TRIMUM_A=1")
        first_p_i = next(i for i, a in enumerate(argv) if a == "-p")
        sep_i = argv.index("--")
        assert unit_i < wd_i < first_setenv_i < first_p_i < sep_i

    def test_env_workdir_ignored_when_unsupported(self):
        orig = ["/bin/bash", "-c", "echo degraded"]
        cmd = sl.build_command(
            orig, "x", systemd_ok=False,
            env={"TRIMUM_A": "1"}, workdir="/tmp/agentdir",
        )
        assert cmd.state == sl.STATE_UNSUPPORTED
        assert list(cmd.argv) == orig, "降级必须原样返回、不加 --setenv / --working-directory"
        assert "--setenv=" not in " ".join(cmd.argv)
        assert "--working-directory=" not in " ".join(cmd.argv)

    def test_non_trimum_keys_dropped(self):
        cmd = sl.build_command(
            ["true"], "x", systemd_ok=True,
            env={"MYVAR": "x", "TRIMUM_A": "1"},
        )
        setenvs = [a for a in cmd.argv if a.startswith("--setenv=")]
        assert setenvs == ["--setenv=TRIMUM_A=1"], "非 TRIMUM_ 前缀键必须被丢弃"


class TestState:
    def test_current_state_only_two_values(self):
        assert sl.current_state() in {sl.STATE_SYSTEMD, sl.STATE_UNSUPPORTED}

    def test_systemd_available_is_bool_no_raise(self):
        assert isinstance(sl.systemd_available(), bool)

    def test_state_constants(self):
        assert sl.STATE_SYSTEMD == "systemd"
        assert sl.STATE_UNSUPPORTED == "unsupported"


class TestNoSpawnLiterals:
    def test_module_has_no_spawn_literals(self):
        text = (os.path.join(os.path.dirname(__file__), "..", "src",
                             "trimum_core", "sandbox_limits.py"))
        body = open(text, encoding="utf-8").read()
        for literal in ("subprocess", "popen", "os.system"):
            assert literal not in body, f"模块里不许出现 {literal!r}"


class TestParseSize:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (2048, 2048),
            ("2048", 2048),
            ("1GiB", 1073741824),
            ("512MiB", 536870912),
            ("1G", 1073741824),
            ("1.5GiB", 1610612736),
            ("0", 0),
        ],
    )
    def test_valid(self, value, expected):
        assert sl.parse_size(value) == expected

    @pytest.mark.parametrize(
        "value",
        ["-1", "", "abc", "1XB", None, 1.5],
    )
    def test_invalid_raises(self, value):
        with pytest.raises(ValueError):
            sl.parse_size(value)


class TestFromMapping:
    def test_none_and_empty_equal_defaults(self):
        assert sl.Limits.from_mapping(None) == sl.Limits()
        assert sl.Limits.from_mapping({}) == sl.Limits()

    def test_all_four_keys(self):
        limits = sl.Limits.from_mapping(
            {
                "memory_max": "512MiB",
                "memory_swap_max": "1GiB",
                "cpu_quota_percent": 25,
                "tasks_max": 16,
            }
        )
        assert limits.memory_max_bytes == 536870912
        assert limits.memory_swap_max_bytes == 1073741824
        assert limits.cpu_quota_percent == 25
        assert limits.tasks_max == 16

    def test_unknown_key_raises_and_names_key(self):
        with pytest.raises(ValueError) as excinfo:
            sl.Limits.from_mapping({"memory_maxs": "1GiB"})
        assert "memory_maxs" in str(excinfo.value)

    def test_invalid_value_raises_via_post_init(self):
        with pytest.raises(ValueError):
            sl.Limits.from_mapping({"memory_max": "0"})
