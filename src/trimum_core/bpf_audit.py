"""eBPF 审计源（daemon 侧）：把特权 helper 的回灌转成 `security.ebpf_alert`（观测失败只 log，不上抛）。"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .event_bus import EVENT_SEC_EBPF
from .models import AuditEvent

# ---- 常量（逐字） ----
DEFAULT_ALERT_PATH: str = "/run/trimum-bpf/bpf-alerts.jsonl"  # 兜底默认；真机由单元 Environment=TRIMUM_BPF_ALERTS 覆盖
ALERT_PATH_ENV: str = "TRIMUM_BPF_ALERTS"
ALERT_PATH_CONFIG_KEY: str = "security.bpf_alerts"
DEFAULT_POLL_INTERVAL_SECONDS: float = 2.0
ALERT_INTERVAL_ENV: str = "TRIMUM_BPF_ALERT_INTERVAL"
ALERT_INTERVAL_CONFIG_KEY: str = "security.bpf_alert_interval"
EVENT_SOURCE: str = "bpf-helper"
#: helper 回灌里认得的 kind。前四个是 `bpf_guard` 的产物；`exec` 是 `exec_guard` 的产物
#: （kind 数值表见 `bpf/trimum_bpf.h` ⇄ `bpf_loader.KINDS`）。不在这个表里的一律丢。
HELPER_ALERT_KINDS: tuple[str, ...] = ("bpf_attach", "bpf_detach", "prog_load", "map_write", "exec")
MAX_LINE_BYTES: int = 4096
MAX_COMM_LEN: int = 64
MAX_DETAIL_LEN: int = 500

log = logging.getLogger("trimum_core.bpf_audit")


@dataclass(frozen=True)
class BpfAlert:
    kind: str
    pid: int = 0
    comm: str = ""
    detail: str = ""


def alert_path(
    *,
    explicit: str | os.PathLike[str] | None = None,
    config: object | None = None,
) -> Path:
    """回灌文件路径，优先级与 `bpf_helper_protocol.manifest_path` **完全同口径**：
    显式参数 > env `TRIMUM_BPF_ALERTS` > `config.get("security.bpf_alerts")` > 默认。
    `config` 只 duck-typing 调 `.get(...)`；**缺失 / 空串 / 非字符串 / 取值抛异常 ⇒ 静默走默认**（不许抛）。
    返回 `Path(...)`，不 expanduser / resolve / 建目录。
    """
    if explicit is not None:
        return Path(explicit)
    env_value = os.environ.get(ALERT_PATH_ENV)
    if env_value is not None and env_value.strip():
        return Path(env_value)
    if config is not None:
        try:
            value = config.get(ALERT_PATH_CONFIG_KEY)
        except Exception:
            value = None
        if isinstance(value, str) and value:
            return Path(value)
    return Path(DEFAULT_ALERT_PATH)


def parse_alert_line(line: "str | bytes") -> Optional[BpfAlert]:
    """helper 回灌的一行 ⇒ `BpfAlert`；任何不合规 ⇒ `None`（**静默丢弃，不抛**）。

    判据（顺序随意，但逐条都要有）：
    - bytes ⇒ `utf-8` 解码，失败 ⇒ None；`strip()` 后为空 ⇒ None；
    - 长度 > `MAX_LINE_BYTES` ⇒ None；`json.loads` 失败 / 顶层非 dict ⇒ None；
    - `kind` 必须是 str 且在 `HELPER_ALERT_KINDS` 内 ⇒ 否则 None；
    - `pid`（缺省 0）必须是 int、**不是 bool**、`>= 0` ⇒ 否则 None；
    - `comm`（缺省 ""）必须是 str ⇒ 否则 None；**超长截断**到 `MAX_COMM_LEN`（不拒）；
    - `detail`（缺省 ""）必须是 str ⇒ 否则 None；**超长截断**到 `MAX_DETAIL_LEN`（不拒）；
    - 顶层白名单外的键**忽略**（不拒：文件是 root 写的，读侧宽容）。
    """
    if isinstance(line, bytes):
        try:
            text = line.decode("utf-8")
        except UnicodeDecodeError:
            return None
    elif isinstance(line, str):
        text = line
    else:
        return None

    text = text.strip()
    if not text:
        return None
    if len(text) > MAX_LINE_BYTES:
        return None
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None

    kind = obj.get("kind")
    if not isinstance(kind, str) or kind not in HELPER_ALERT_KINDS:
        return None

    pid = obj.get("pid", 0)
    if isinstance(pid, bool) or not isinstance(pid, int) or pid < 0:
        return None

    comm = obj.get("comm", "")
    if not isinstance(comm, str):
        return None
    if len(comm) > MAX_COMM_LEN:
        comm = comm[:MAX_COMM_LEN]

    detail = obj.get("detail", "")
    if not isinstance(detail, str):
        return None
    if len(detail) > MAX_DETAIL_LEN:
        detail = detail[:MAX_DETAIL_LEN]

    return BpfAlert(kind=kind, pid=pid, comm=comm, detail=detail)


def to_bus_payload(alert: BpfAlert) -> dict[str, Any]:
    """固定四键：`{"kind","pid","comm","detail"}`（键集必须逐字一致，多一个少一个都算错）。"""
    return {
        "kind": alert.kind,
        "pid": alert.pid,
        "comm": alert.comm,
        "detail": alert.detail,
    }


def to_audit_event(alert: BpfAlert, *, timestamp: float | None = None) -> AuditEvent:
    """`AuditEvent(event_type=EVENT_SEC_EBPF, source_type=EVENT_SOURCE, risk="high",
    action="alert", reason=f"eBPF helper 告警：{alert.kind}", details=to_bus_payload(alert),
    timestamp=time.time() if timestamp is None else timestamp)`。
    其余字段留 `AuditEvent` 默认值；**不要**给 `event_id` / `hmac` / `prev_hash` 填值（审计链由 `AuditStore` 负责）。
    """
    return AuditEvent(
        event_type=EVENT_SEC_EBPF,
        source_type=EVENT_SOURCE,
        risk="high",
        action="alert",
        reason=f"eBPF helper 告警：{alert.kind}",
        details=to_bus_payload(alert),
        timestamp=time.time() if timestamp is None else timestamp,
    )


def read_new_alerts(
    path: "str | os.PathLike[str]", offset: int
) -> tuple[list[BpfAlert], int]:
    """从 `offset` 读新行，返回 `(alerts, new_offset)`。**任何失败都不上抛**。

    口径：
    - `offset` 不是 int / 为负 ⇒ 按 0 处理；
    - 文件打不开（不存在 / 权限 / 是目录）⇒ 返回 `([], offset)`，只 `log.debug`；
    - 文件当前大小 `< offset`（被截断 / 轮转）⇒ `offset` 归 0 重读；
    - 按 `\\n` 切行；**最后一段没有结尾 `\\n` 的算半行**：本次不消费它（`new_offset` 停在半行起点），下次补齐后再读；
    - 每行交给 `parse_alert_line`；返回 `None` 的行**照样消费**（坏行不许卡住后续）。
    """
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        offset = 0

    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except (OSError, ValueError):
        log.debug("bpf_alerts: 无法读取 %s，保持 offset=%d", path, offset)
        return [], offset

    if len(data) < offset:
        offset = 0

    if offset >= len(data):
        return [], offset

    chunk = data[offset:]
    end = chunk.rfind(b"\n")
    if end < 0:
        # 整段都是半行（无结尾 \n）：本次不消费任何内容
        return [], offset

    full = chunk[: end + 1]
    new_offset = offset + len(full)
    alerts: list[BpfAlert] = []
    for raw_line in full.split(b"\n"):
        if not raw_line:
            continue
        alert = parse_alert_line(raw_line)
        if alert is not None:
            alerts.append(alert)
    return alerts, new_offset


async def publish_alert(
    alert: BpfAlert,
    *,
    bus: object | None = None,
    audit_store: object | None = None,
) -> bool:
    """发事件 + 落审计；返回是否**至少成功一步**。

    - `bus is not None` ⇒ `await bus.emit_event(event_type=EVENT_SEC_EBPF, source=EVENT_SOURCE,
      payload=to_bus_payload(alert))`（**传的就是不带前缀的常量**，前缀由 `EventBus` 自己加）；
    - `audit_store is not None` ⇒ `audit_store.append(to_audit_event(alert))`；
    - 任一步抛异常 ⇒ `log.warning(...)` 并返回 False，**绝不向上抛**；
    - 两个都为 None ⇒ 返回 False（什么都没做）。
    """
    succeeded = False
    if bus is not None:
        try:
            await bus.emit_event(
                event_type=EVENT_SEC_EBPF,
                source=EVENT_SOURCE,
                payload=to_bus_payload(alert),
            )
            succeeded = True
        except Exception:
            log.warning("bpf_alerts: bus.emit_event 失败（kind=%s）", alert.kind, exc_info=True)
    if audit_store is not None:
        try:
            audit_store.append(to_audit_event(alert))
            succeeded = True
        except Exception:
            log.warning("bpf_alerts: audit_store.append 失败（kind=%s）", alert.kind, exc_info=True)
    return succeeded


class BpfAlertTailer:
    """按位置增量读回灌文件的游标（内存态即可，不落盘）。"""

    def __init__(
        self,
        path: "str | os.PathLike[str] | None" = None,
        *,
        config: object | None = None,
    ) -> None:
        """`path is None` ⇒ 用 `alert_path(config=config)`；`self._offset = 0`。"""
        self._path: Path = Path(path) if path is not None else alert_path(config=config)
        self._offset: int = 0

    @property
    def path(self) -> Path:
        return self._path

    @property
    def offset(self) -> int:
        return self._offset

    def seek_end(self) -> int:
        """把 offset 推到**当前文件末尾**（文件不存在 ⇒ 0）；返回新 offset。daemon 启动时调它，
        避免重启后把历史行整段重放。**不许抛**。"""
        try:
            self._offset = os.path.getsize(self._path)
        except (OSError, ValueError):
            self._offset = 0
        return self._offset

    def poll(self) -> list[BpfAlert]:
        """`read_new_alerts(self.path, self._offset)` → 推进 offset → 返回 alerts。**不许抛**。"""
        try:
            alerts, new_offset = read_new_alerts(self._path, self._offset)
        except Exception:
            log.warning("bpf_alerts: poll 读取 %s 失败", self._path, exc_info=True)
            return []
        self._offset = new_offset
        return alerts


def alert_interval(
    *,
    explicit: float | None = None,
    config: object | None = None,
) -> float:
    """回灌轮询间隔（秒）。优先级 **显式 > env `TRIMUM_BPF_ALERT_INTERVAL` >
    `config.get("security.bpf_alert_interval")` > 默认 `DEFAULT_POLL_INTERVAL_SECONDS`**。
    任一层「缺失 / 空 / 非数字 / 非正数 / 取值抛异常」⇒ 记一句 `log.warning` 后**落到下一层**，
    底层是默认值。**不许抛、不许返回 <= 0**（0 会让轮询忙等）。`bool` 不算数字（`True` 要当坏值）。
    """
    if explicit is not None:
        if (
            isinstance(explicit, (int, float))
            and not isinstance(explicit, bool)
            and explicit > 0
        ):
            return float(explicit)
        log.warning("bpf_audit.bad_interval_explicit: %r", explicit)

    raw = os.environ.get(ALERT_INTERVAL_ENV, "")
    raw = raw.strip()
    if raw:
        try:
            value = float(raw)
        except ValueError:
            value = None
        if value is not None and value > 0:
            return value
        log.warning("bpf_audit.bad_interval_env: %r", raw)

    if config is not None:
        try:
            value = config.get(ALERT_INTERVAL_CONFIG_KEY)
        except Exception:
            value = None
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value > 0
        ):
            return float(value)

    return DEFAULT_POLL_INTERVAL_SECONDS


class BpfAlertPoller:
    """把 `BpfAlertTailer`（增量读回灌文件）接上 `publish_alert`（事件 + 审计）的常驻轮询器。

    形状照 `audit_watchdog.AuditWatchdog`：构造存引用 + `seek_end()`（**不回放历史**）；
    `run_forever()` 循环 `poll_once()` → `sleep(interval)`；`CancelledError` 放行。
    """

    def __init__(
        self,
        *,
        bus: object | None = None,
        audit_store: object | None = None,
        tailer: BpfAlertTailer | None = None,
        interval: float | None = None,
        config: object | None = None,
        path: "str | os.PathLike[str] | None" = None,
    ) -> None:
        """`tailer` 给了就用它（此时 `path` 忽略）；否则 `BpfAlertTailer(path, config=config)`。
        `self.interval = alert_interval(explicit=interval, config=config)`（**一切走这一个函数，别自己写 float()**）。
        `self._bus` / `self._audit_store` 原样存（可以是 None）。"""
        self._bus = bus
        self._audit_store = audit_store
        self._tailer: BpfAlertTailer = (
            tailer
            if tailer is not None
            else BpfAlertTailer(path, config=config)
        )
        self.interval: float = alert_interval(explicit=interval, config=config)
        # 构造即 seek_end：把历史跳过。放构造里（同步、无 to_thread）是因为
        # `run_forever` 是 `create_task` 调度的协程，测试里「startup 返回后立即写新行」
        # 会跑在 `seek_end` 之前 ⇒ 首轮 poll 读到历史。构造里同步做，时序就稳了。
        self._tailer.seek_end()

    @property
    def tailer(self) -> BpfAlertTailer:
        return self._tailer

    @property
    def path(self) -> Path:
        return self._tailer.path

    async def poll_once(self) -> int:
        """读一轮并逐条发出去；返回本轮 alert 条数。**绝不向上抛。**

        口径（逐条）：
        - `alerts = await asyncio.to_thread(self._tailer.poll)` —— `poll()` 是同步文件 IO（整份读），
          **必须**丢线程，不许在事件循环里直跑；
        - `to_thread` 抛（理论上不会，但兜住）⇒ `log.warning("bpf_audit.poll_failed", ...)` 后 `return 0`；
        - 否则按顺序 `for alert in alerts: await publish_alert(alert, bus=self._bus, audit_store=self._audit_store)`
          （`publish_alert` 自己吞异常）；
        - 返回 `len(alerts)`。
        """
        try:
            alerts = await asyncio.to_thread(self._tailer.poll)
        except Exception as exc:  # noqa: BLE001
            log.warning("bpf_audit.poll_failed: %s (path=%s)", exc, self.path)
            return 0
        for alert in alerts:
            await publish_alert(alert, bus=self._bus, audit_store=self._audit_store)
        return len(alerts)

    async def run_forever(self) -> None:
        """`while True:` → `await self.poll_once()` → `await asyncio.sleep(self.interval)`。
        `asyncio.CancelledError` 必须 `raise`（关停靠它）；其它异常兜底
        `log.warning("bpf_audit.poller_crashed", ...)` 后继续循环（轮询器自己不许死）。
        **不做 `interval <= 0` 的特殊分支**（`alert_interval` 已保证 > 0）。
        历史已在 `__init__` 里 `seek_end()` 跳过，这里直接进增量循环。"""
        while True:
            try:
                await self.poll_once()
                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("bpf_audit.poller_crashed: %s", exc)
