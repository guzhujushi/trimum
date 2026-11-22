"""Non-interactive consoles must not approve high-risk operations."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from trimum_core.cli.commands.ask import _QuietConsole


@pytest.mark.asyncio
async def test_quiet_console_confirm_fails_closed():
    console = _QuietConsole()
    assert await console.confirm("执行以上操作?", default=False) is False
    assert await console.confirm("确认开始执行计划?") is False
