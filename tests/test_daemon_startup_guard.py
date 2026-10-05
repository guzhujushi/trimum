"""启动看门狗回归（docs/SANDBOX-PLAN.md §9.3.8 发现 1 续篇，TODO dboot1）。

`ContextManager` 的 aiosqlite 连接线程是非 daemon 线程，初始化**中途**失败时
`sys.exit` 会被它吊住（真机实测 `timeout 90` 只能 SIGKILL、退出码 124 而非 3）。
本文件钉住三件事：

1. 超时值解析 env > 配置 `core.startup_timeout_seconds` > 默认 60（坏值静默走默认）；
2. 看门狗是 daemon Timer，且能被 lifespan startup 钩子 / 挂不上时手动拆掉；
3. 子进程回归：初始化 hang 会被看门狗硬退（exit 3）、初始化抛异常同样硬退（exit 3）。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from trimum_core import main  # noqa: E402

SRC = str(Path(__file__).resolve().parents[1] / "src")


class _Cfg:
    """最小 config 替身：只支持 `get(key, default)`。"""

    def __init__(self, v=None):
        self._v = v

    def get(self, k, d=None):
        return self._v if self._v is not None else d


def test_timeout_prefers_env_then_config_then_default(monkeypatch):
    # ① env 无 + 配置无 ⇒ 默认 60.0
    monkeypatch.delenv(main.STARTUP_TIMEOUT_ENV, raising=False)
    assert main._startup_timeout(_Cfg(None)) == 60.0

    # ② env 压过配置：env=2.5、配置给 99 也回 2.5
    monkeypatch.setenv(main.STARTUP_TIMEOUT_ENV, "2.5")
    assert main._startup_timeout(_Cfg(99)) == 2.5

    # ③ env 删掉 + 配置给 7 ⇒ 7.0
    monkeypatch.delenv(main.STARTUP_TIMEOUT_ENV, raising=False)
    assert main._startup_timeout(_Cfg(7)) == 7.0

    # ④ 坏值：env "abc" 与 配置 0 ⇒ 都回默认 60.0
    monkeypatch.setenv(main.STARTUP_TIMEOUT_ENV, "abc")
    assert main._startup_timeout(_Cfg(None)) == 60.0
    monkeypatch.delenv(main.STARTUP_TIMEOUT_ENV, raising=False)
    assert main._startup_timeout(_Cfg(0)) == 60.0


def test_arm_watchdog_returns_live_daemon_timer_and_disarms():
    t = main._arm_startup_watchdog(_Cfg(30))
    try:
        assert t.is_alive() is True
        assert t.daemon is True
    finally:
        t.cancel()
    _wait_dead(t)
    assert not t.is_alive()


def test_attach_disarm_hook_cancels_timer_via_lifespan_startup():
    class _Router:
        def __init__(self):
            self.on_startup = []

    class _App:
        def __init__(self):
            self.router = _Router()

    class _Bad:
        pass

    app = _App()
    timer = main._arm_startup_watchdog(_Cfg(30))
    main._attach_watchdog_disarm(app, timer)
    assert timer.is_alive() is True
    for handler in list(app.router.on_startup):
        handler()
    _wait_dead(timer)
    assert not timer.is_alive()

    # 挂不上（没有 .router）⇒ 必须手动拆，不许悬着
    timer2 = main._arm_startup_watchdog(_Cfg(30))
    main._attach_watchdog_disarm(_Bad(), timer2)
    _wait_dead(timer2)
    assert not timer2.is_alive()


def _wait_dead(timer: "threading.Timer", timeout: float = 5.0) -> None:
    """`Timer.cancel()` 是异步的：已 start 的线程要跑完当前 wait 才真正停。"""
    deadline = time.monotonic() + timeout
    while timer.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)


def _ensure_log_dir(tmp_path: Path) -> None:
    """`setup_logging` 会 `open(config.log_path, "a")`；子进程里该路径由
    `XDG_DATA_HOME` 推出（`<data>/trimum/trimum.log`），先建好父目录。"""
    (tmp_path / "data" / "trimum").mkdir(parents=True, exist_ok=True)
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    (tmp_path / "trimum").mkdir(parents=True, exist_ok=True)


def _guard_env(tmp_path: Path) -> dict:
    return {
        **os.environ,
        "TRIMUM_STARTUP_TIMEOUT_SECONDS": "1",
        "TRIMUM_HTTP": "0",
        "TRIMUM_SOCKET": str(tmp_path / "x.sock"),
        "XDG_CONFIG_HOME": str(tmp_path / "cfg"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_RUNTIME_DIR": str(tmp_path / "run"),
        "HOME": str(tmp_path / "home"),
        "TRIMUM_HOME": str(tmp_path / "trimum"),
    }


def test_startup_hang_is_killed_by_watchdog(tmp_path):
    _ensure_log_dir(tmp_path)
    code = (
        "import sys, time\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "import trimum_core.api_server as api\n"
        "import trimum_core.main as m\n"
        "def _hang(config):\n"
        "    time.sleep(300)\n"
        "api.create_app = _hang\n"
        "sys.argv = [\"trmd\"]\n"
        "m.run()\n"
    )
    start = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-c", code, SRC],
        env=_guard_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=60,
    )
    elapsed = time.monotonic() - start
    assert proc.returncode == 3
    assert "启动中止" in proc.stderr
    assert elapsed < 20


def test_init_exception_is_hard_exit(tmp_path):
    _ensure_log_dir(tmp_path)
    code = (
        "import sys, threading, time\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "import trimum_core.api_server as api\n"
        "import trimum_core.main as m\n"
        "def _boom(config):\n"
        "    raise RuntimeError('boom-init')\n"
        "api.create_app = _boom\n"
        "threading.Thread(target=time.sleep, args=(300,)).start()\n"
        "sys.argv = [\"trmd\"]\n"
        "m.run()\n"
    )
    # 看门狗必须**远远晚于**本子进程的超时：否则 soft `sys.exit` 被非 daemon 线程吊住时，
    # 1s 的看门狗会替 `hard=True` 兜底，把「这个分支是否真的硬退」的判据掩盖掉
    # （2026-10-05 ds 实测 M4 未变红就是这个原因）。
    env = {**_guard_env(tmp_path), "TRIMUM_STARTUP_TIMEOUT_SECONDS": "300"}
    t0 = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-c", code, SRC],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert time.monotonic() - t0 < 15
    assert proc.returncode == 3
    assert "初始化失败" in proc.stderr
