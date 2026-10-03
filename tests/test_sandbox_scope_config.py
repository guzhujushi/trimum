"""S6① 键名与单位收敛后的配置面用例：``SecurityConfig`` 顶层 ``limits:`` 段。

只验证配置读取与 ``Limits.from_mapping`` 的衔接（**不接线**：
``agent_launcher`` 的接入是下一片，这里不碰）。
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from trimum_core import sandbox_limits as sl  # noqa: E402
from trimum_core.security_config import SecurityConfig  # noqa: E402


@pytest.fixture()
def cfg_path(tmp_path):
    return tmp_path / "security.yaml"


class TestLimitsSection:
    def test_builtin_defaults_when_file_missing(self, cfg_path):
        cfg = SecurityConfig(path=cfg_path)
        limits = cfg.get_limits()
        assert limits["memory_max"] == "1GiB"
        assert limits["cpu_quota_percent"] == 100
        assert limits["tasks_max"] == 128

    def test_user_file_deep_merges_over_defaults(self, cfg_path):
        cfg_path.write_text(
            "limits:\n  memory_max: 256MiB\n", encoding="utf-8"
        )
        cfg = SecurityConfig(path=cfg_path)
        limits = cfg.get_limits()
        assert limits["memory_max"] == "256MiB"
        # 其余键仍为内置默认（深合并，不是整段替换）
        assert limits["memory_swap_max"] == 0
        assert limits["cpu_quota_percent"] == 100
        assert limits["tasks_max"] == 128

    def test_from_mapping_consumes_get_limits(self, cfg_path):
        cfg_path.write_text(
            "limits:\n  memory_max: 256MiB\n", encoding="utf-8"
        )
        cfg = SecurityConfig(path=cfg_path)
        limits = sl.Limits.from_mapping(cfg.get_limits())
        assert limits.memory_max_bytes == 268435456


class TestRegression:
    def test_sandbox_config_still_readable(self, cfg_path):
        cfg = SecurityConfig(path=cfg_path)
        sandbox = cfg.get_sandbox_config()
        assert sandbox["mode"] == "workspace-write"
        assert sandbox["fail_closed"] is True

    def test_levels_no_longer_carry_resource_limits(self, cfg_path):
        cfg = SecurityConfig(path=cfg_path)
        assert "resource_limits" not in cfg.get_level_config(cfg.get_mode())
        assert "resource_limits" not in cfg._raw["levels"]["balanced"]
        assert "resource_limits" not in cfg._raw["levels"]["sandbox"]


class TestAgentAllowWrite:
    """S6③：运营者显式授权的写面（``agents.<name>.allow_write``）。"""

    def test_missing_file_returns_empty(self, cfg_path):
        cfg = SecurityConfig(path=cfg_path)
        assert cfg.get_agent_allow_write("probe") == []

    def test_unknown_agent_and_empty_name_return_empty(self, cfg_path):
        cfg = SecurityConfig(path=cfg_path)
        assert cfg.get_agent_allow_write("nope") == []
        assert cfg.get_agent_allow_write("") == []

    def test_user_file_is_returned(self, cfg_path):
        cfg_path.write_text(
            'agents:\n  probe:\n    allow_write:\n      - "/tmp/x"\n', encoding="utf-8"
        )
        cfg = SecurityConfig(path=cfg_path)
        assert cfg.get_agent_allow_write("probe") == ["/tmp/x"]

    def test_bad_types_do_not_raise(self, cfg_path):
        cfg_path.write_text(
            'agents:\n  probe:\n    allow_write: "not-a-list"\n', encoding="utf-8"
        )
        cfg = SecurityConfig(path=cfg_path)
        # 单个字符串按「一条路径」处理（与 sandbox_exec._as_paths 同口径），不抛异常
        assert cfg.get_agent_allow_write("probe") == ["not-a-list"]

    def test_dirty_items_are_dropped(self, cfg_path):
        cfg_path.write_text(
            'agents:\n  probe:\n    allow_write: ["", "  ", 123, null, "/tmp/ok"]\n',
            encoding="utf-8",
        )
        cfg = SecurityConfig(path=cfg_path)
        assert cfg.get_agent_allow_write("probe") == ["/tmp/ok"]

    def test_mode_and_allow_write_coexist(self, cfg_path):
        cfg_path.write_text(
            'agents:\n  probe:\n    mode: "sandbox"\n    allow_write: ["/tmp/x"]\n',
            encoding="utf-8",
        )
        cfg = SecurityConfig(path=cfg_path)
        assert cfg.get_agent_allow_write("probe") == ["/tmp/x"]
        assert cfg.get_mode("probe").value == "sandbox"

    def test_builtin_defaults_grant_nobody(self, cfg_path):
        # 内置默认里只许有注释示例，不许给任何 agent 写死授权
        cfg = SecurityConfig(path=cfg_path).load()
        assert (cfg._raw.get("agents") or {}) == {}
        assert cfg.get_agent_allow_write("probe") == []


from trimum_core import sandbox_exec as sx  # noqa: E402


class TestValidateScope:
    """S6⑤：``validate_scope`` 文案（不读真机 ~/.trimum，全部指向 tmp）。"""

    def test_skipped_message_has_no_space_between_label_and_里的路径(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg_config"))
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg_data"))
        sx.reset_cache()
        # manifest 的 sandbox 段用键 read 声明一个不存在的路径：必走 skipped 的 manifest 分支
        manifest = {"sandbox": {"read": ["~/never_exists_dir_xyz"]}}
        problems = sx.validate_scope("probe", manifest=manifest)
        hit = [p for p in problems if "段里的路径" in p["message"]]
        assert hit, f"分支没走到：{[p['message'] for p in problems]}"
        assert not any("段 里的路径" in p["message"] for p in problems)
