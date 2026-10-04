"""Tool directory resolution via ``data_dir`` (env → config → default).

Covers the "config-first, no hardcoding" rule: the tools directory must be
resolved through the shared helper instead of a literal ``~/.trimum/tools``.
Every test is fully isolated via ``tmp_path`` + ``monkeypatch`` and never
touches the real ``~/.trimum``.
"""

from __future__ import annotations

from pathlib import Path


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
