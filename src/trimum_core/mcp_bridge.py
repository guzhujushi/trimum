"""MCP 工具聚合 —— 把远端 ``tools/list`` 变成 ToolRegistry 里的一等条目。

一个远端工具在 trimum 里的名字是 ``<server>__<tool>``：定义名只允许
``[a-z0-9_-]``，而 ``<tool>`` 原样保留，所以一个名字里出现 ``__`` 就说明它是
聚合出来的（``split_name`` 按**第一个** ``__`` 切）。

**为什么是缓存而不是实时拉取**：M4 之后 MCP server 是懒启动 + 空闲回收的，
如果「列一下远端工具」得先把每个 server 拉起来，这份清单就把懒启动整个抵消
掉了。所以 ``MCPToolIndex`` 只记「上一次成功列出的结果」：server 因为别的原因
被列过工具时顺手写下，读的时候不启动任何进程。

**失效规则**：条目带定义指纹（会改变工具集合的那些字段）。定义变了、或者
server 被删掉，旧条目就不该再冒充可用工具 —— ``record()`` 每次整份替换该
server 的条目，``forget()`` 用来手动清一个 server。
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from .logger import get_logger
from .models import RiskLevel, ToolDefinition, ToolType
from .paths import trimum_path

log = get_logger("mcp_bridge")

#: 聚合名的分隔符（``<server>__<tool>``）。
NAME_SEPARATOR = "__"

#: 缓存文件（可指向别处，便于测试与多 profile）。
INDEX_ENV = "TRIMUM_MCP_INDEX"
INDEX_FILENAME = "mcp-tools.json"


def default_index_path() -> Path:
    """缓存文件位置：``TRIMUM_MCP_INDEX`` 优先，否则 ``~/.trimum/mcp-tools.json``。"""
    override = os.environ.get(INDEX_ENV)
    if override and override.strip():
        return Path(override).expanduser()
    return trimum_path(INDEX_FILENAME)


def flat_name(server: str, tool: str) -> str:
    """``("filesystem", "read_file")`` → ``"filesystem__read_file"``。"""
    return f"{server}{NAME_SEPARATOR}{tool}"


def split_name(name: str) -> tuple[str, str] | None:
    """``"filesystem__read_file"`` → ``("filesystem", "read_file")``。

    不是聚合名（没有分隔符、或某一侧为空）时返回 ``None``；工具名里再出现
    ``__`` 没关系，只有第一个分隔符算数。
    """
    server, sep, tool = (name or "").strip().partition(NAME_SEPARATOR)
    if not sep or not server or not tool:
        return None
    return server, tool


def fingerprint(definition: Any) -> str:
    """定义里「会影响有哪些工具」的那些字段的指纹。

    只取键名不取值：``env`` / ``headers`` 里通常是密钥，不该进缓存文件，
    而它们改值一般也不改变工具集合。
    """
    payload = {
        "transport": definition.transport,
        "command": definition.command,
        "args": list(definition.args),
        "env_keys": sorted(definition.env),
        "url": definition.url,
        "header_keys": sorted(definition.headers),
        "trust": definition.trust,
        "allow_tools": sorted(definition.allow_tools),
        "deny_tools": sorted(definition.deny_tools),
        "enabled": bool(definition.enabled),
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def tool_definition(entry: dict[str, Any]) -> ToolDefinition:
    """把一条聚合条目变成注册表里的 ``ToolDefinition``。"""
    server = str(entry.get("server", ""))
    tool = str(entry.get("tool", ""))
    description = str(entry.get("description", "") or "").strip()
    prefix = f"MCP {server}.{tool}"
    return ToolDefinition(
        name=str(entry.get("name") or flat_name(server, tool)),
        description=f"{prefix} — {description}" if description else prefix,
        tool_type=ToolType.MCP_TOOLS_CALL,
        timeout_default=float(entry.get("timeout") or 30.0),
        risk_level=RiskLevel(str(entry.get("risk") or RiskLevel.MEDIUM.value)),
    )


class MCPToolIndex:
    """每个 server 上一次成功 ``tools/list`` 的结果（落盘，读不启动进程）。"""

    def __init__(self, path: str | Path | None = None, *, clock: Any = None) -> None:
        self.path = Path(path) if path is not None else default_index_path()
        self._clock = clock or time.time
        self._servers: dict[str, dict[str, Any]] = {}
        self._loaded = False

    # ------------------------------------------------------------------
    # 读写
    # ------------------------------------------------------------------

    def load(self) -> dict[str, dict[str, Any]]:
        """读缓存；文件不存在或坏了都当成「还没有缓存」，不抛异常。"""
        self._loaded = True
        self._servers = {}
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        except OSError as exc:
            log.warning("mcp_index.unreadable", path=str(self.path), error=str(exc))
            return {}
        try:
            data = json.loads(raw)
        except ValueError as exc:
            # 缓存坏了不是错误：下一次 record() 会重写它
            log.warning("mcp_index.corrupt", path=str(self.path), error=str(exc))
            return {}
        servers = data.get("servers") if isinstance(data, dict) else None
        if isinstance(servers, dict):
            self._servers = {
                str(name): dict(entry)
                for name, entry in servers.items()
                if isinstance(entry, dict)
            }
        return dict(self._servers)

    def _ensure(self) -> None:
        if not self._loaded:
            self.load()

    def save(self) -> None:
        """原子写（临时文件 + rename），失败只记警告。"""
        payload = {
            "version": 1,
            "updated_at": round(float(self._clock()), 3),
            "servers": self._servers,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(tmp, self.path)
        except OSError as exc:  # 缓存写不进去不该影响调用
            log.warning("mcp_index.unwritable", path=str(self.path), error=str(exc))

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def servers(self) -> dict[str, dict[str, Any]]:
        self._ensure()
        return {name: dict(entry) for name, entry in self._servers.items()}

    def entries(self) -> dict[str, dict[str, Any]]:
        """``{<server>__<tool>: 条目}``，供 ToolRegistry 直接注册。"""
        self._ensure()
        out: dict[str, dict[str, Any]] = {}
        for server, block in sorted(self._servers.items()):
            for tool in block.get("tools") or []:
                if not isinstance(tool, dict):
                    continue
                name = flat_name(server, str(tool.get("name", "")))
                if name.endswith(NAME_SEPARATOR):
                    continue
                out[name] = {
                    "name": name,
                    "server": server,
                    "tool": str(tool.get("name", "")),
                    "description": str(tool.get("description", "") or ""),
                    "input_schema": tool.get("input_schema") or {},
                    "trust": block.get("trust", "local"),
                    "transport": block.get("transport", "stdio"),
                    "risk": block.get("risk", RiskLevel.MEDIUM.value),
                    "timeout": block.get("timeout", 30.0),
                    "updated_at": block.get("updated_at"),
                }
        return out

    def to_tool_definitions(self) -> list[ToolDefinition]:
        return [tool_definition(entry) for entry in self.entries().values()]

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def record(self, definition: Any, tools: list[dict[str, Any]]) -> int:
        """整份替换某个 server 的工具条目并落盘，返回条目数。

        整份替换（而不是并集）是刻意的：server 撤掉一个工具之后，旧名字必须
        跟着消失，否则 Agent 会拿着一个指向不存在工具的名字去调用。
        """
        self._ensure()
        self._servers[str(definition.name)] = {
            "fingerprint": fingerprint(definition),
            "transport": definition.transport,
            "trust": definition.trust,
            "risk": definition.risk,
            "timeout": float(definition.timeout),
            "updated_at": round(float(self._clock()), 3),
            "tools": [
                {
                    "name": str(tool.get("name", "")),
                    "description": str(tool.get("description", "") or ""),
                    "input_schema": tool.get("input_schema") or {},
                }
                for tool in tools
                if isinstance(tool, dict) and str(tool.get("name", "")).strip()
            ],
        }
        self.save()
        return len(self._servers[str(definition.name)]["tools"])

    def forget(self, server: str) -> bool:
        """删掉一个 server 的全部条目（定义被移除、或用户要求重新探测）。"""
        self._ensure()
        removed = self._servers.pop(str(server), None) is not None
        if removed:
            self.save()
        return removed

    def prune(self, known: Any) -> int:
        """丢掉不在 ``known`` 里的 server，返回丢掉的数量。

        缓存里的名字是给 Agent 看的：留一个指向「定义已经删掉」的 server，
        调用必然失败，而失败信息在调用方看来像是 ``mcp.tools.call`` 自己坏
        了。所以定义被删 / 改名时要连着清。

        注意 ``known`` 为空会把整份缓存清空 —— 调用方要先分清「一个 server
        都没有」和「读不出有哪些 server」。
        """
        self._ensure()
        keep = {str(name) for name in known}
        gone = sorted(name for name in self._servers if name not in keep)
        for name in gone:
            del self._servers[name]
        if gone:
            self.save()
            log.info("mcp_index.pruned", removed=gone)
        return len(gone)


__all__ = [
    "NAME_SEPARATOR",
    "INDEX_ENV",
    "INDEX_FILENAME",
    "default_index_path",
    "flat_name",
    "split_name",
    "fingerprint",
    "tool_definition",
    "MCPToolIndex",
]
