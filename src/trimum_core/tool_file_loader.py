"""Tool File Loader — load tool definitions from JSON5 manifest files.

Scans ~/.trimum/tools/<name>/tool.json5 and registers them into ToolRegistry.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

# Use json5 if available, fallback to json with comment stripping
try:
    import json5  # pip install json5
    HAS_JSON5 = True
except ImportError:
    HAS_JSON5 = False

from .models import ToolDefinition, ToolType, RiskLevel

log = logging.getLogger("trimum_core.tool_file_loader")

# ── Schema defaults ─────────────────────────────────────

TOOL_KINDS: dict[str, ToolType] = {
    "shell": ToolType.SHELL,
    "file_read": ToolType.FILE_READ,
    "file_write": ToolType.FILE_WRITE,
    "file_delete": ToolType.FILE_DELETE,
    "file_list": ToolType.FILE_LIST,
    "file_move": ToolType.FILE_MOVE,
    "file_copy": ToolType.FILE_COPY,
    "file_search": ToolType.FILE_SEARCH,
    "git": ToolType.GIT,
    "git_status": ToolType.GIT_STATUS,
    "git_diff": ToolType.GIT_DIFF,
    "git_log": ToolType.GIT_LOG,
    "git_commit": ToolType.GIT_COMMIT,
    "git_push": ToolType.GIT_PUSH,
    "git_pull": ToolType.GIT_PULL,
    "git_branch": ToolType.GIT_BRANCH,
    "http": ToolType.HTTP,
    "http_get": ToolType.HTTP_GET,
    "http_post": ToolType.HTTP_POST,
    "process": ToolType.PROCESS,
    "process_list": ToolType.PROCESS_LIST,
    "process_kill": ToolType.PROCESS_KILL,
    "system": ToolType.SYSTEM,
    "system_info": ToolType.SYSTEM_INFO,
    "system_disk": ToolType.SYSTEM_DISK,
    "system_memory": ToolType.SYSTEM_MEMORY,
    "knowledge_search": ToolType.KNOWLEDGE_SEARCH,
    "knowledge_store": ToolType.KNOWLEDGE_STORE,
    "notification": ToolType.NOTIFICATION,
    "notification_send": ToolType.NOTIFICATION_SEND,
    "mcp_tools_list": ToolType.MCP_TOOLS_LIST,
    "mcp_tools_call": ToolType.MCP_TOOLS_CALL,
    "env_get": ToolType.ENV_GET,
    "env_list": ToolType.ENV_LIST,
    "browser": ToolType.BROWSER,
    "custom": ToolType.CUSTOM,
}

RISK_MAP: dict[str, RiskLevel] = {
    "low": RiskLevel.LOW,
    "medium": RiskLevel.MEDIUM,
    "high": RiskLevel.HIGH,
    "critical": RiskLevel.CRITICAL,
}


def strip_json_comments(text: str) -> str:
    """Strip JS-style comments from JSON text (fallback when json5 not available)."""
    import re as _re
    # Strip single-line // comments
    text = _re.sub(r'//[^\n]*', '', text)
    # Strip multi-line /* */ comments
    text = _re.sub(r'/\*.*?\*/', '', text, flags=_re.DOTALL)
    return text


#: manifest 里 ``enabled`` 那一行（JSON5 形态，允许带引号、允许行尾逗号）。
_ENABLED_LINE_RE = re.compile(r'^(\s*)"?enabled"?\s*:\s*(true|false)\s*(,?)\s*$', re.M)


def load_manifest(path: Path) -> Optional[dict]:
    """Return the raw manifest dict of one ``tool.json5`` (None if unreadable)."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        log.warning("Cannot read tool manifest %s: %s", path, e)
        return None

    try:
        if HAS_JSON5:
            data = json5.loads(raw)
        else:
            data = json.loads(strip_json_comments(raw))
    except (json.JSONDecodeError, ValueError) as e:
        log.warning("Invalid JSON5 in %s: %s", path, e)
        return None

    return data if isinstance(data, dict) else None


def manifest_enabled(data: Optional[dict]) -> bool:
    """Whether a manifest is enabled.

    Missing ``enabled`` means enabled: every tool that existed before E4 keeps
    working untouched.  Imported third-party tools are written with an explicit
    ``enabled: false`` (registration is not authorization).
    """
    if not data:
        return False
    return bool(data.get("enabled", True))


def is_enabled(path: Path) -> bool:
    """Whether the manifest at *path* is enabled (unreadable => not enabled)."""
    return manifest_enabled(load_manifest(path))


def set_manifest_enabled(path: Path, enabled: bool) -> bool:
    """Flip ``enabled`` in a manifest **in place**, preserving comments.

    A hand-written JSON5 manifest must not be rewritten as plain JSON just
    because someone ran ``trm tool disable`` - so this edits the one line (or
    inserts one right after the opening brace).
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        log.warning("Cannot read tool manifest %s: %s", path, e)
        return False

    value = "true" if enabled else "false"
    new_text, count = _ENABLED_LINE_RE.subn(
        lambda m: f'{m.group(1)}"enabled": {value}{m.group(3)}', text
    )
    if count == 0:
        brace = text.find("{")
        if brace < 0:
            return False
        insert_at = brace + 1
        new_text = text[:insert_at] + f'\n    "enabled": {value},' + text[insert_at:]

    path.write_text(new_text, encoding="utf-8", newline="\n")
    return True


def list_manifests(base_path: Optional[str] = None) -> list[dict]:
    """Every ``tool.json5`` on disk, enabled or not (for ``trm tool list --all``).

    Unlike :func:`scan_tools` (kept as-is for compatibility), the default root
    here honours ``TRIMUM_HOME`` — the E4 importers resolve their target through
    that same root, so "what I imported" and "what I can list" cannot drift.
    """
    if base_path:
        tools_dir = Path(base_path)
    else:
        from .paths import trimum_path

        tools_dir = trimum_path("tools")
    if not tools_dir.is_dir():
        return []

    found: list[dict] = []
    for child in sorted(tools_dir.iterdir()):
        if not child.is_dir():
            continue
        manifest_path = child / "tool.json5"
        if not manifest_path.is_file():
            continue
        data = load_manifest(manifest_path)
        found.append(
            {
                "name": child.name,
                "path": str(manifest_path),
                "enabled": manifest_enabled(data),
                "manifest": data or {},
            }
        )
    return found


def parse_tool_manifest(path: Path) -> Optional[ToolDefinition]:
    """Parse a single tool.json5 file into a ToolDefinition.

    Expected JSON5 format::

        {
            name: "git",
            description: "Git operations: status, diff, log, commit, push, pull",
            kind: "git",
            entry: "./main.py",
            language: "python",
            timeout: 30.0,
            risk: "medium",
            permissions: {
                filesystem: ["project/read", "project/write"],
                network: true,
            },
            tools: ["shell"],  # tool dependencies (not implemented in v1)
        }
    """
    data = load_manifest(path)
    if data is None:
        return None

    name = data.get("name", path.parent.name)
    kind_str = data.get("kind", "custom")
    tool_type = TOOL_KINDS.get(kind_str, ToolType.CUSTOM)

    risk_str = data.get("risk", "medium")
    risk = RISK_MAP.get(risk_str, RiskLevel.MEDIUM)

    timeout = float(data.get("timeout", 30.0))
    description = data.get("description", "")
    entry = data.get("entry", "./main.py")

    # Allowed flags (optional)
    allowed_flags = data.get("allowed_flags", [])

    return ToolDefinition(
        name=name,
        description=description,
        tool_type=tool_type,
        executable=str(path.parent / entry),
        allowed_flags=allowed_flags,
        timeout_default=timeout,
        risk_level=risk,
    )


def scan_tools(
    base_path: Optional[str] = None,
    *,
    include_disabled: bool = False,
) -> list[ToolDefinition]:
    """Scan ~/.trimum/tools/ for tool.json5 manifests.

    Returns a list of ToolDefinitions (one per valid manifest).  Disabled
    manifests (``enabled: false``) are skipped unless *include_disabled* is set.
    """
    if base_path is None:
        base_path = str(Path.home() / ".trimum" / "tools")

    tools_dir = Path(base_path)
    if not tools_dir.is_dir():
        log.info("Tools directory not found: %s", tools_dir)
        return []

    found: list[ToolDefinition] = []
    for child in sorted(tools_dir.iterdir()):
        if not child.is_dir():
            continue
        manifest_path = child / "tool.json5"
        if not manifest_path.is_file():
            log.debug("Skipping %s: no tool.json5", child.name)
            continue
        if not include_disabled and not is_enabled(manifest_path):
            log.info("Skipping %s: disabled in tool.json5", child.name)
            continue
        tool_def = parse_tool_manifest(manifest_path)
        if tool_def is not None:
            tool_def.name = child.name  # directory name overrides
            found.append(tool_def)
            log.info("Loaded tool: %s (%s)", tool_def.name, tool_def.tool_type.value)

    return found
