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

import pytest


@pytest.fixture(autouse=True, scope="session")
def isolated_trimum_home(tmp_path_factory):
    """Keep every test out of the developer's real ``~/.trimum``."""
    home = tmp_path_factory.mktemp("trimum-home")
    os.environ["TRIMUM_HOME"] = str(home)
    return home
