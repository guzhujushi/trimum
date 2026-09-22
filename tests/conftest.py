"""Shared test setup.

Nothing in this suite may touch the developer's real ``~/.trimum``: a leftover
``mcp-tools.json`` (or a tool someone dropped into ``~/.trimum/tools``) would
change what ``ToolRegistry`` reports and make the result depend on the machine
the tests happen to run on.  Point the data root at a throwaway directory for
the whole session.  Tests that need their own root still call
``monkeypatch.setenv("TRIMUM_HOME", ...)``, which wins because it is applied
later.
"""

from __future__ import annotations

import os
import sys

import pytest

# 让 conftest 自己的 fixture 也能 import trimum_core（测试模块各自还会再 insert 一次）
_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


@pytest.fixture(autouse=True, scope="session")
def isolated_trimum_home(tmp_path_factory):
    """Keep every test out of the developer's real ``~/.trimum``."""
    home = tmp_path_factory.mktemp("trimum-home")
    os.environ["TRIMUM_HOME"] = str(home)
    return home


@pytest.fixture(autouse=True)
def reset_llm_router_state():
    """llm_router 的令牌桶与冷却是**进程级**状态，用例之间必须隔离。

    否则前一个用例撞出来的 429/超时冷却会漏到下一个用例，表现成「primary 被跳过」，
    看起来像路由坏了。
    """
    try:
        from trimum_core import llm_router
    except ImportError:  # 没装包时不要因此挂掉
        yield
        return
    llm_router.reset_state()
    yield
    llm_router.reset_state()


@pytest.fixture(autouse=True)
def reset_sandbox_exec_state():
    """``sandbox_exec`` 的能力探测与配置都是**进程级**缓存，用例之间必须隔离。

    否则前一个用例的 ``TRIMUM_SANDBOX`` / 假 ABI 会漏到下一个用例，表现成
    「档位没变」或「本机突然支持 Landlock」。
    """
    try:
        from trimum_core import sandbox_exec
    except ImportError:  # 没装包时不要因此挂掉
        yield
        return
    sandbox_exec.reset_cache()
    yield
    sandbox_exec.reset_cache()


@pytest.fixture(autouse=True)
def isolate_process_env():
    """用例之间隔离 **进程级** 环境变量。

    ``env_file.ensure_loaded()`` 会把 .env 写进 ``os.environ``（设计如此：CLI 一进来
    就该看到 .env），而它是模块级「只加载一次」。于是只要有一个用例跑了 ``cli.main()``，
    开发机上真实的 ``~/.trimum/.env`` 与仓库根 ``.env`` 就会留在 ``os.environ`` 里，
    后面的用例会读到**开发机的密钥与模型配置**：``test_transform_agent`` 的 base_url
    被 .env 顶掉、``test_env_list_sorted`` 首行变成 ``163_EMAIL=...`` 都是这么来的。
    用例之间必须快照/还原，否则结果取决于跑测试那台机器的 .env。
    """
    snapshot = dict(os.environ)
    try:
        from trimum_core import env_file
    except ImportError:  # 没装包时不要因此挂掉
        env_file = None
    if env_file is not None:
        env_file.reset_loaded()
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(snapshot)
        if env_file is not None:
            env_file.reset_loaded()
