"""Tool directory resolution via ``data_dir`` (env → config → default).

Covers the "config-first, no hardcoding" rule: the tools directory must be
resolved through the shared helper instead of a literal ``~/.trimum/tools``.
Every test is fully isolated via ``tmp_path`` + ``monkeypatch`` and never
touches the real ``~/.trimum``.
"""

from __future__ import annotations

from pathlib import Path
import os
import types

import pytest


def test_data_dir_default(tmp_path, monkeypatch):
    """No env, empty config → falls back to ``<TRIMUM_HOME>/tools``."""
    from trimum_core.config import Config
    from trimum_core.paths import data_dir

    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("TRIMUM_TOOLS_DIR", raising=False)
    cfg = Config(config_path=tmp_path / "none.yaml")
    assert data_dir("tools", env="TRIMUM_TOOLS_DIR", config=cfg) == tmp_path / "home" / "tools"


def test_data_dir_env_override(tmp_path, monkeypatch):
    """A non-empty env var wins over config and default."""
    from trimum_core.config import Config
    from trimum_core.paths import data_dir

    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("TRIMUM_TOOLS_DIR", str(tmp_path / "t-env"))
    cfg = Config(config_path=tmp_path / "none.yaml")
    assert data_dir("tools", env="TRIMUM_TOOLS_DIR", config=cfg) == tmp_path / "t-env"


def test_data_dir_config_override(tmp_path, monkeypatch):
    """Config ``paths.tools`` is used when env is unset."""
    from trimum_core.config import Config
    from trimum_core.paths import data_dir

    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("TRIMUM_TOOLS_DIR", raising=False)
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(f"paths:\n  tools: {tmp_path / 't-cfg'}\n", encoding="utf-8")
    cfg = Config(config_path=cfg_path)
    assert data_dir("tools", env="TRIMUM_TOOLS_DIR", config=cfg) == tmp_path / "t-cfg"


def test_data_dir_env_beats_config(tmp_path, monkeypatch):
    """When both are present, env wins over the config file."""
    from trimum_core.config import Config
    from trimum_core.paths import data_dir

    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("TRIMUM_TOOLS_DIR", str(tmp_path / "t-env"))
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(f"paths:\n  tools: {tmp_path / 't-cfg'}\n", encoding="utf-8")
    cfg = Config(config_path=cfg_path)
    assert data_dir("tools", env="TRIMUM_TOOLS_DIR", config=cfg) == tmp_path / "t-env"


def test_scan_and_executor_follow_trimum_home(tmp_path, monkeypatch):
    """End-to-end: with TRIMUM_HOME swapped and no env/config, a tool under the
    swapped root is discovered and gets an executor — proof the loader no longer
    reads the host ``~/.trimum/tools``.
    """
    from trimum_core.config import Config
    from trimum_core.tool_file_loader import scan_tools
    from trimum_core.tool_gateway import ToolRegistry

    root = tmp_path / "home"
    tools_dir = root / "tools" / "demo"
    tools_dir.mkdir(parents=True)
    (tools_dir / "tool.json5").write_text(
        "{\n"
        '    name: "demo",\n'
        '    description: "demo tool",\n'
        '    kind: "custom",\n'
        '    entry: "./main.py",\n'
        '    language: "python",\n'
        '    timeout: 30.0,\n'
        '    risk: "medium",\n'
        "}\n",
        encoding="utf-8",
    )
    (tools_dir / "main.py").write_text(
        'async def execute(request):\n'
        '    return {"status": "allowed"}\n',
        encoding="utf-8",
    )

    monkeypatch.setenv("TRIMUM_HOME", str(root))
    monkeypatch.delenv("TRIMUM_TOOLS_DIR", raising=False)
    registry = ToolRegistry()
    executor = registry.get_executor("demo")
    assert executor is not None
    assert callable(executor)

    names = {tool.name for tool in scan_tools()}
    assert "demo" in names


def test_skill_loader_defaults_to_trimum_home(tmp_path, monkeypatch):
    """SkillLoader() 无参时落在 <TRIMUM_HOME>/skills，不再读宿主 ~/.trimum。"""
    from pathlib import Path
    from trimum_core.skill_loader import SkillLoader

    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("TRIMUM_SKILLS_DIR", raising=False)
    assert Path(SkillLoader().get_skills_path()) == tmp_path / "home" / "skills"


def test_skill_loader_env_override(tmp_path, monkeypatch):
    """TRIMUM_SKILLS_DIR 非空时压过默认目录。"""
    from pathlib import Path
    from trimum_core.skill_loader import SkillLoader

    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("TRIMUM_SKILLS_DIR", str(tmp_path / "s-env"))
    assert Path(SkillLoader().get_skills_path()) == tmp_path / "s-env"


def test_skill_loader_config_override(tmp_path, monkeypatch):
    """env 为空时用配置 paths.skills。"""
    from pathlib import Path
    from trimum_core import config as config_mod
    from trimum_core.skill_loader import SkillLoader

    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("TRIMUM_SKILLS_DIR", raising=False)
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"paths:\n  skills: {tmp_path / 's-cfg'}\n", encoding="utf-8")
    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_PATH", cfg)
    assert Path(SkillLoader().get_skills_path()) == tmp_path / "s-cfg"


def test_agent_registry_follows_trimum_home(tmp_path, monkeypatch):
    """AgentRegistry 无 base_path 时读 <TRIMUM_HOME>/agents：空目录返回 0、能读到 manifest。"""
    from trimum_core.agent_registry import AgentRegistry

    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("TRIMUM_AGENTS_DIR", raising=False)

    reg = AgentRegistry()
    assert reg.load_from_dir() == 0

    agent_dir = tmp_path / "home" / "agents" / "demo"
    agent_dir.mkdir(parents=True)
    (agent_dir / "agent.json5").write_text(
        '{\n    name: "demo",\n    version: "1.0.0",\n    capabilities: ["demo.echo"],\n}\n',
        encoding="utf-8",
    )
    manifest = AgentRegistry().read_manifest("demo")
    assert manifest is not None
    assert manifest.name == "demo"


def test_default_workflow_dir_follows_trimum_home(tmp_path, monkeypatch):
    """planner_agent.default_workflow_dir() 懒解析，随 TRIMUM_HOME 变。"""
    from pathlib import Path
    from trimum_core.planner_agent import default_workflow_dir

    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("TRIMUM_WORKFLOWS_DIR", raising=False)
    assert default_workflow_dir() == Path(tmp_path / "home" / "workflows")

def test_agents_root_env_and_default(tmp_path, monkeypatch):
    """agents_root(): env 覆盖 > 默认（XDG 数据目录）；不吃宿主 ~/.trimum / ~/.local。"""
    from trimum_core import agent_launcher as al

    monkeypatch.delenv("TRIMUM_AGENTS_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert al.agents_root() == tmp_path / "xdg" / "trimum" / "agents"

    monkeypatch.setenv("TRIMUM_AGENTS_DIR", str(tmp_path / "a-env"))
    assert al.agents_root() == tmp_path / "a-env"


def test_xdg_data_dir_env_and_default(tmp_path, monkeypatch):
    """xdg_data_dir(): env 覆盖 > 默认（Path.home() 兜底属允许项）。"""
    from trimum_core.paths import xdg_data_dir

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert xdg_data_dir("agents") == tmp_path / "xdg" / "trimum" / "agents"

    monkeypatch.delenv("XDG_DATA_HOME")
    monkeypatch.setenv("HOME", str(tmp_path / "host"))
    assert xdg_data_dir() == tmp_path / "host" / ".local" / "share" / "trimum"


def test_read_pid_file_follows_trimum_home(tmp_path, monkeypatch):
    """read_pid_file：配置 daemon.pid_path 最优先 > TRIMUM_HOME > 缺文件 None。"""
    from trimum_core.cli._utils import read_pid_file

    class _Cfg:
        def get(self, key, default=None):
            return default

    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True)
    pid_file = tmp_path / "home" / "trimum.pid"
    pid_file.write_text("4242\n", encoding="utf-8")
    assert read_pid_file(_Cfg()) == 4242

    configured = tmp_path / "cfg.pid"
    configured.write_text("777\n", encoding="utf-8")

    class _CfgWithPid:
        def get(self, key, default=None):
            if key == "daemon.pid_path":
                return str(configured)
            return default

    assert read_pid_file(_CfgWithPid()) == 777

    class _CfgEmpty:
        def get(self, key, default=None):
            return default

    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "empty"))
    assert read_pid_file(_CfgEmpty()) is None


def test_plan_for_uses_shared_xdg_helper(tmp_path, monkeypatch):
    """sandbox_exec 数据目录走 paths.xdg_data_dir helper 而不是就地拼路径。"""
    from trimum_core import sandbox_exec as sx

    sentinel = str(tmp_path / "sentinel-data")
    monkeypatch.setattr(sx, "xdg_data_dir", lambda *a: sentinel)
    sx.reset_cache()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "home"))
    plan = sx.plan_for(None, cwd=str(tmp_path), mode="readonly")
    assert sentinel in set(plan.sources) | {entry["path"] for entry in plan.skipped}


def test_security_config_default_path_follows_trimum_home(tmp_path, monkeypatch):
    """SecurityConfig 默认路径走 paths helper，随 TRIMUM_HOME 变。"""
    from trimum_core.security_config import SecurityConfig

    home = tmp_path / "home"
    monkeypatch.setenv("TRIMUM_HOME", str(home))
    assert SecurityConfig._default_path() == home / "security.yaml"

    explicit = tmp_path / "explicit.yaml"
    assert SecurityConfig(path=explicit).path == explicit


def test_file_trust_default_db_path_follows_trimum_home(tmp_path, monkeypatch):
    """FileTrustTracker 默认 db 路径走 paths helper，且父目录被创建。"""
    from trimum_core.file_trust import FileTrustTracker

    home = tmp_path / "home"
    monkeypatch.setenv("TRIMUM_HOME", str(home))
    tracker = FileTrustTracker()
    assert tracker.db_path == home / "data" / "file_trust.db"
    assert (home / "data").is_dir()


def test_memory_root_follows_trimum_home(tmp_path, monkeypatch):
    """memory root 候选随 TRIMUM_HOME 变。"""
    from trimum_core.cli.commands.memory import _resolve_memory_root

    home = tmp_path / "home"
    monkeypatch.setenv("TRIMUM_HOME", str(home))
    monkeypatch.delenv("TRIMUM_MEMORY_DIR", raising=False)
    cfg = types.SimpleNamespace(context_db_path=str(tmp_path / "ctx" / "context.db"))
    assert _resolve_memory_root(cfg) == home / "memory"


def test_client_socket_candidates_follow_xdg_data(tmp_path, monkeypatch):
    """trimum_client 的数据目录候选：① 跟随 XDG_DATA_HOME；② 调用点真的接的是 paths helper。

    判别力在 ②：spy 掉模块里的 ``xdg_data_dir`` 后，它必须被调用、且返回值进候选列表；
    把调用点改回就地拼 ``XDG_DATA_HOME/trimum/trimum.sock`` ⇒ 本用例必红。
    """
    from trimum_core import trimum_client

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert tmp_path / "xdg" / "trimum" / "trimum.sock" in trimum_client.socket_candidates()

    sentinel = tmp_path / "sentinel" / "trimum.sock"
    monkeypatch.setattr(trimum_client, "xdg_data_dir", lambda *a: sentinel)
    assert sentinel in trimum_client.socket_candidates()


def test_doctor_directories_follow_trimum_home(tmp_path, monkeypatch):
    """doctor 目录检查的 base 随 TRIMUM_HOME 变。"""
    from trimum_core.cli.commands.doctor import _check_directories

    home = tmp_path / "home"
    monkeypatch.setenv("TRIMUM_HOME", str(home))
    assert _check_directories()["base"] == str(home)


def test_health_config_fallback_follows_trimum_home(tmp_path, monkeypatch):
    """health 配置检查的 fallback 路径随 TRIMUM_HOME 变。"""
    monkeypatch.setattr(
        "trimum_core.config.Config",
        lambda *a, **k: types.SimpleNamespace(config_path=tmp_path / "missing.yaml"),
    )
    from trimum_core.cli.commands.health import _check_config

    home = tmp_path / "home"
    monkeypatch.setenv("TRIMUM_HOME", str(home))
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text("{}", encoding="utf-8")
    assert _check_config()["exists"] is True


# ---- 配置**读不到**（EACCES）⇒ 静默走默认，不许抛 --------------------------------
#
# 真机场景（2026-10-06 `trimum-bpf-helper` 实测）：以 root 跑 + systemd `ProtectHome=yes` 的服务里，
# 默认配置路径 `~/.config/trimum/config.yaml` 就是 `/root/.config/...`（整个 /root 不可达），
# 而 `Path.exists()` 只吞 ENOENT 一类，`EACCES` 会原样抛 ⇒ `Config()` 把进程带走、单元 crash-loop。

def _blocked_config_file(tmp_path: Path, text: str, name: str = "config.yaml") -> Path:
    """写一份配置再把**父目录**设成 0000：对非 root 进程，stat 其下任何路径都是 EACCES。"""
    if os.geteuid() == 0:
        pytest.skip("root 不受目录权限限制，模拟不出 EACCES")
    d = tmp_path / "blocked"
    d.mkdir()
    p = d / name
    p.write_text(text, encoding="utf-8")
    os.chmod(d, 0o000)
    return p


def test_config_unreadable_path_falls_back_to_defaults(tmp_path):
    """读不到（EACCES）的配置文件 ⇒ 不抛异常，且**不**套用它里面的值。"""
    from trimum_core.config import Config

    p = _blocked_config_file(tmp_path, "core:\n  port: 9999\n")
    try:
        cfg = Config(config_path=p)          # 旧行为：PermissionError
        assert cfg.get("core.port") != 9999  # 读不到的那份不该生效
    finally:
        os.chmod(p.parent, 0o755)


def test_policy_loader_unreadable_path_uses_default_rules(tmp_path):
    """policy 也走同一条静默口径，别在装/起服务时炸。"""
    from trimum_core.config import PolicyLoader

    p = _blocked_config_file(tmp_path, "rules:\n  - name: nope\n", name="policy.yaml")
    try:
        rules = PolicyLoader(p).load()       # 旧行为：PermissionError
        assert isinstance(rules, list)
    finally:
        os.chmod(p.parent, 0o755)
