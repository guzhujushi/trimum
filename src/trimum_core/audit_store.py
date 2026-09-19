"""AuditStore — 结构化审计日志（JSONL）。

Phase 3 收尾 P1：审计此前只有 structlog 文本行 + 进程内环缓冲，无法按字段查询。
现在每条 ``AuditEvent`` 落一行 JSON，``trm log audit`` 直接读文件过滤，
进程内同时通过 EventBus 广播 ``task.audit.<event_type>``。

设计取舍：
- 写入失败绝不抛出（审计是旁路，不能拖垮执行路径）
- 单行 JSONL，便于 grep / jq / 流式 tail
- 超过 ``max_bytes`` 时轮转为 ``<name>.1``（只保留一份备份）
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterable, Optional

from .models import AuditEvent

log = logging.getLogger("trimum_core.audit_store")

DEFAULT_AUDIT_FILENAME = "audit.jsonl"


def default_audit_path() -> Path:
    """审计文件默认位置：与主日志同目录的 ``audit.jsonl``。"""
    from .config import Config

    return Path(Config().log_path).parent / DEFAULT_AUDIT_FILENAME


class AuditStore:
    """JSONL 审计日志读写。"""

    def __init__(self, path: Optional[str | Path] = None, max_bytes: int = 5 * 1024 * 1024) -> None:
        self.path = Path(path) if path is not None else default_audit_path()
        self.max_bytes = max_bytes

    # ------------------------------------------------------------------
    # 写
    # ------------------------------------------------------------------

    def append(self, event: AuditEvent) -> bool:
        """追加一条审计事件，返回是否成功（失败不抛异常）。"""
        line = json.dumps(event.model_dump(), ensure_ascii=False, default=str)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate_if_needed()
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            return True
        except Exception as e:  # 审计失败不能影响主流程
            log.debug("audit_store.append_failed: %s", e)
            return False

    def _rotate_if_needed(self) -> None:
        try:
            if self.path.exists() and self.path.stat().st_size >= self.max_bytes:
                backup = self.path.with_suffix(self.path.suffix + ".1")
                backup.unlink(missing_ok=True)
                self.path.rename(backup)
        except OSError as e:
            log.debug("audit_store.rotate_failed: %s", e)

    # ------------------------------------------------------------------
    # 读
    # ------------------------------------------------------------------

    def read(self) -> list[dict[str, Any]]:
        """读取全部审计事件（坏行跳过）。"""
        return list(self._iter_events())

    def query(
        self,
        *,
        since: Optional[float] = None,
        event_type: Optional[str] = None,
        agent_id: Optional[str] = None,
        risk: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """按字段过滤，返回最近 ``limit`` 条（时间正序）。"""
        matched = [
            event
            for event in self._iter_events()
            if self._matches(event, since=since, event_type=event_type, agent_id=agent_id, risk=risk)
        ]
        if limit and limit > 0:
            matched = matched[-limit:]
        return matched

    @staticmethod
    def _matches(
        event: dict[str, Any],
        *,
        since: Optional[float],
        event_type: Optional[str],
        agent_id: Optional[str],
        risk: Optional[str],
    ) -> bool:
        if since is not None:
            try:
                if float(event.get("timestamp", 0)) < since:
                    return False
            except (TypeError, ValueError):
                return False
        if event_type and event.get("event_type") != event_type:
            return False
        if agent_id and event.get("agent_id") != agent_id:
            return False
        if risk and event.get("risk") != risk:
            return False
        return True

    def _iter_events(self) -> Iterable[dict[str, Any]]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        events = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return events


__all__ = ["AuditStore", "DEFAULT_AUDIT_FILENAME", "default_audit_path"]