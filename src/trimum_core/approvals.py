"""一次性审批请求通道（A2）。

为什么：现在高风险操作只有 CLI 能弹窗确认——`SecurityRule.confirm()` 是
「把 user_response 传进去」的纯函数，web / API / workflow 这些非交互通道
拿到 `confirm` 决策后没有路可走，只能全放行或全拒。本模块提供一条**一次性**
审批请求通道：请求方（任意进程）落盘一条 pending 请求，人在 CLI 上用
`trm approve` 批准/拒绝，请求方再 `consume()` 一次性取走结果。

口径（2026-10-05 定）：
- 落点 `data_dir("approvals", env="TRIMUM_APPROVALS_DIR")`，默认
  `<TRIMUM_HOME>/approvals/`；一请求一文件 `<id>.json`，原子写、权限 0600。
- TTL 优先级：显式参数 > `TRIMUM_APPROVAL_TTL` > 配置 `approvals.ttl_seconds`
  > 300 秒；解析失败 / <=0 一律回 300。
- **过期即 fail-closed**：过期记录记为 `expired`，任何路径都不得当成放行。
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

from .paths import data_dir

log = logging.getLogger("trimum_core.approvals")

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_DENIED = "denied"
STATUS_EXPIRED = "expired"
STATUS_CONSUMED = "consumed"

DEFAULT_TTL_SECONDS = 300.0
TTL_ENV = "TRIMUM_APPROVAL_TTL"
DIR_ENV = "TRIMUM_APPROVALS_DIR"

# 终态：进入其一后状态不可再改变（fail-closed 的落点）。
_TERMINAL_STATUSES = (
    STATUS_APPROVED,
    STATUS_DENIED,
    STATUS_EXPIRED,
    STATUS_CONSUMED,
)

_KNOWN_FIELDS = (
    "id",
    "agent_id",
    "tool",
    "command",
    "cwd",
    "risk_level",
    "reason",
    "created_at",
    "expires_at",
    "status",
    "decided_at",
    "decided_by",
    "used_at",
)


@dataclass
class ApprovalRequest:
    """一条一次性审批请求（落盘为 `<id>.json`）。"""

    id: str
    agent_id: str = ""
    tool: str = ""
    command: str = ""
    cwd: str = ""
    risk_level: str = ""
    reason: str = ""
    created_at: float = 0.0
    expires_at: float = 0.0
    status: str = STATUS_PENDING
    decided_at: float = 0.0
    decided_by: str = ""
    used_at: float = 0.0

    def is_expired(self, now: float | None = None) -> bool:
        """pending 且已过期 ⇒ True（已决/已消费的记录不再算过期）。"""
        if self.status != STATUS_PENDING:
            return False
        return (now if now is not None else time.time()) >= self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ApprovalRequest":
        """只取已知字段：未知键忽略、缺失用默认。"""
        return cls(**{key: data[key] for key in _KNOWN_FIELDS if key in data})


def load_allow_rules(config: Any = None) -> list[dict[str, Any]]:
    """读配置 ``approvals.allow`` 声明式放行表。缺失/坏配置/类型不对 ⇒ []（静默走默认，不许抛）。"""
    try:
        if config is None:
            from .config import Config

            config = Config()
        raw = config.get("approvals.allow", None)
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    return [rule for rule in raw if isinstance(rule, dict)]


def match_allow_rules(rules: Any, *, tool: str = "", cwd: str = "") -> bool:
    """声明式放行匹配：tool 精确（空=任意）+ cwd 前缀（空=任意）；非 list / 异常 ⇒ False（fail-closed）。"""
    if not isinstance(rules, list):
        return False
    try:
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            rule_tool = rule.get("tool", "") or ""
            if rule_tool and rule_tool != tool:
                continue
            rule_cwd = rule.get("cwd", "")
            if not (cwd or "").startswith(rule_cwd):
                continue
            return True
        return False
    except Exception:
        return False


class ApprovalStore:
    """一次性审批请求的文件存储（web/API/workflow 与 CLI 共用同一份落盘）。"""

    def __init__(
        self,
        directory: str | Path | None = None,
        *,
        default_ttl: float | None = None,
        clock: Any = None,
        config: Any = None,
    ) -> None:
        # directory 为 None ⇒ 走配置口径（env > config > 默认），配置缺失静默走默认。
        self._directory = (
            Path(directory)
            if directory is not None
            else data_dir("approvals", env=DIR_ENV)
        )
        self._default_ttl = default_ttl
        self._clock = clock or time.time
        self._config = config

    @property
    def directory(self) -> Path:
        return self._directory

    def request(
        self,
        *,
        agent_id: str = "",
        tool: str = "",
        command: str = "",
        cwd: str = "",
        risk_level: str = "",
        reason: str = "",
        ttl: float | None = None,
    ) -> ApprovalRequest:
        """创建一条 pending 请求并落盘，返回记录。"""
        now = float(self._clock())
        record = ApprovalRequest(
            id=uuid.uuid4().hex[:16],
            agent_id=agent_id,
            tool=tool,
            command=command,
            cwd=cwd,
            risk_level=risk_level,
            reason=reason,
            created_at=now,
            expires_at=now + self._parse_ttl(ttl),
        )
        self._write(record)
        return record

    def get(self, request_id: str) -> Optional[ApprovalRequest]:
        """读一条记录；找不到 / 坏 JSON / 不可读 ⇒ None（静默，不抛）。

        读到 pending 且已过期 ⇒ 就地写回 expired 再返回（fail-closed 落盘）。
        """
        record = self._read(request_id)
        if record is None:
            return None
        if record.is_expired():
            record.status = STATUS_EXPIRED
            self._write(record)
        return record

    def decide(
        self,
        request_id: str,
        *,
        approved: bool,
        decided_by: str = "user",
    ) -> Optional[ApprovalRequest]:
        """批准/拒绝一条 pending 请求。

        **fail-closed**：已是终态或已过期 ⇒ 不改变状态，原样返回
        （过期时先落盘 expired）。只有 pending 且未过期才落盘决策。
        记录不存在 ⇒ None。
        """
        record = self._read(request_id)
        if record is None:
            return None
        if record.is_expired():
            record.status = STATUS_EXPIRED
            self._write(record)
            return record
        if record.status != STATUS_PENDING:
            return record
        record.status = STATUS_APPROVED if approved else STATUS_DENIED
        record.decided_at = float(self._clock())
        record.decided_by = decided_by
        self._write(record)
        return record

    def consume(self, request_id: str) -> Optional[ApprovalRequest]:
        """一次性消费：仅 `approved` 且未 used 的记录被翻成 `consumed`。

        其余（pending/denied/expired/已 consumed/不存在）一律原样返回，
        不得当成放行。
        """
        record = self._read(request_id)
        if record is None:
            return None
        if record.is_expired():
            record.status = STATUS_EXPIRED
            self._write(record)
            return record
        if record.status != STATUS_APPROVED:
            return record
        if record.used_at:
            record.status = STATUS_CONSUMED
            self._write(record)
            return record
        record.used_at = float(self._clock())
        record.status = STATUS_CONSUMED
        self._write(record)
        return record

    def list_pending(self) -> list[ApprovalRequest]:
        """扫目录下 `*.json`，只返回未过期的 pending（过期的顺手落盘 expired）。

        坏文件 / 不可读静默跳过，不抛。
        """
        records: list[ApprovalRequest] = []
        if not self._directory.is_dir():
            return records
        for path in sorted(self._directory.glob("*.json")):
            if not path.is_file():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            record = ApprovalRequest.from_dict(data)
            if record.status != STATUS_PENDING:
                continue
            if record.is_expired():
                record.status = STATUS_EXPIRED
                self._write(record)
                continue
            records.append(record)
        return records

    def preauthorized(self, *, tool: str = "", cwd: str = "", config: Any = None) -> bool:
        """声明式放行：tool 精确（空=任意）+ cwd 前缀（空=任意）；无规则/异常 ⇒ False（fail-closed）。"""
        try:
            cfg = config if config is not None else self._config
            return match_allow_rules(load_allow_rules(cfg), tool=tool, cwd=cwd)
        except Exception:
            return False

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _parse_ttl(self, ttl: float | None) -> float:
        """TTL 优先级：显式参数 > env > 配置 `approvals.ttl_seconds` > 300。

        任何解析失败 / <=0 都回默认 300，配置缺失静默走默认（不抛）。
        """
        for raw in (
            ttl,
            os.environ.get(TTL_ENV),
            self._config_ttl(),
            self._default_ttl,
        ):
            if raw is None:
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if value > 0:
                return value
        return DEFAULT_TTL_SECONDS

    def _config_ttl(self) -> Any:
        try:
            if self._config is None:
                from .config import Config

                self._config = Config()
            return self._config.get("approvals.ttl_seconds", None)
        except Exception:
            return None

    def _path(self, request_id: str) -> Path:
        return self._directory / f"{request_id}.json"

    def _read(self, request_id: str) -> Optional[ApprovalRequest]:
        path = self._path(request_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        return ApprovalRequest.from_dict(data)

    def _write(self, record: ApprovalRequest) -> None:
        """原子写：同目录 `<id>.json.tmp` 写完后 os.replace，文件权限 0600。"""
        self._directory.mkdir(parents=True, exist_ok=True)
        final_path = self._path(record.id)
        tmp_path = final_path.with_name(f"{record.id}.json.tmp")
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(record.to_dict(), handle, ensure_ascii=False, indent=2)
            os.replace(tmp_path, final_path)
        except Exception:
            try:
                tmp_path.unlink()
            except OSError:
                pass
            raise


__all__ = [
    "ApprovalRequest",
    "ApprovalStore",
    "load_allow_rules",
    "match_allow_rules",
    "DEFAULT_TTL_SECONDS",
    "STATUS_PENDING",
    "STATUS_APPROVED",
    "STATUS_DENIED",
    "STATUS_EXPIRED",
    "STATUS_CONSUMED",
]
