"""env_file：把 .env 读进 os.environ（已存在的环境变量优先）。

关键约定：
1. 已有环境变量不被 .env 覆盖（systemd / Shell 显式设的更可信）；
2. 只认第一个命中的文件，避免后来者把配置覆盖成「半套」；
3. 候选顺序 TRIMUM_ENV_FILE → $TRIMUM_HOME/.env → ~/.trimum/.env → ./.env。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from trimum_core import env_file


def test_parse_handles_comments_quotes_and_export():
    parsed = env_file.parse_env_file(
        "\n".join([
            "# 注释",
            "",
            "API_KEY=sk-1",
            "export TRIMUM_LLM_MODEL=qwen3.8-27b",
            'QUOTED="a=b c"',
            "SINGLE='x y'",
            "NO_EQUALS_LINE",
            "EMPTY=",
            "   SPACED   =   v   ",
        ])
    )
    assert parsed == {
        "API_KEY": "sk-1",
        "TRIMUM_LLM_MODEL": "qwen3.8-27b",
        "QUOTED": "a=b c",
        "SINGLE": "x y",
        "EMPTY": "",
        "SPACED": "v",
    }


def test_existing_env_wins_unless_override(tmp_path, monkeypatch):
    monkeypatch.delenv("TRIMUM_TEST_NEW", raising=False)
    monkeypatch.setenv("TRIMUM_TEST_KEEP", "from-shell")
    path = tmp_path / ".env"
    path.write_text(
        "TRIMUM_TEST_NEW=from-file\nTRIMUM_TEST_KEEP=from-file\n", encoding="utf-8"
    )

    applied = env_file.load_env_file(path)
    assert applied == {"TRIMUM_TEST_NEW": "from-file"}
    assert os.environ["TRIMUM_TEST_KEEP"] == "from-shell", ".env 不该覆盖已有环境变量"

    env_file.load_env_file(path, override=True)
    assert os.environ["TRIMUM_TEST_KEEP"] == "from-file", "override=True 时才允许覆盖"


def test_candidates_stack_per_key_with_earlier_winning(tmp_path, monkeypatch):
    """多个 .env 叠加：同一个 key 以先出现的文件为准，后面的文件只补缺口。

    （回归：早先「只读第一个命中的文件」会让一个只剩 OPENAI_* 的
    ``~/.trimum/.env`` 把仓库根 .env 整个挡掉。）
    """
    explicit = tmp_path / "explicit.env"
    explicit.write_text("TRIMUM_TEST_SHARED=explicit\nTRIMUM_TEST_ONLY_A=1\n", encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    (home / ".env").write_text("TRIMUM_TEST_SHARED=home\nTRIMUM_TEST_ONLY_B=2\n", encoding="utf-8")

    # 只喂这两个文件，别让开发机上真实的 ~/.trimum/.env 与仓库根 .env 混进来
    monkeypatch.setattr(env_file, "candidate_paths", lambda: [explicit, home / ".env"])
    for name in ("TRIMUM_TEST_SHARED", "TRIMUM_TEST_ONLY_A", "TRIMUM_TEST_ONLY_B"):
        monkeypatch.delenv(name, raising=False)

    applied = env_file.load_env_file()
    assert applied == {
        "TRIMUM_TEST_SHARED": "explicit",
        "TRIMUM_TEST_ONLY_A": "1",
        "TRIMUM_TEST_ONLY_B": "2",
    }
    assert os.environ["TRIMUM_TEST_SHARED"] == "explicit", "先出现的文件优先"


def test_candidate_order(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIMUM_ENV_FILE", str(tmp_path / "a.env"))
    monkeypatch.setenv("TRIMUM_HOME", str(tmp_path / "home"))
    paths = [str(p) for p in env_file.candidate_paths()]
    assert paths[0] == str(tmp_path / "a.env")
    assert paths[1] == str(tmp_path / "home" / ".env")
    assert any(p.endswith(".trimum" + os.sep + ".env") or p.endswith(".trimum/.env") for p in paths[2:])
    assert paths[-1].endswith(".env")


def test_missing_file_is_a_noop(tmp_path, monkeypatch):
    monkeypatch.delenv("TRIMUM_TEST_MISSING", raising=False)
    assert env_file.load_env_file(tmp_path / "nope.env") == {}
    assert "TRIMUM_TEST_MISSING" not in os.environ


def test_ensure_loaded_runs_once(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("TRIMUM_TEST_ONCE=1\n", encoding="utf-8")
    monkeypatch.setenv("TRIMUM_ENV_FILE", str(path))
    monkeypatch.delenv("TRIMUM_TEST_ONCE", raising=False)
    monkeypatch.setattr(env_file, "_loaded", False)

    env_file.ensure_loaded()
    assert os.environ["TRIMUM_TEST_ONCE"] == "1"
    os.environ.pop("TRIMUM_TEST_ONCE")
    env_file.ensure_loaded()
    assert "TRIMUM_TEST_ONCE" not in os.environ, "第二次调用不该重复加载"
