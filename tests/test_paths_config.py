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
