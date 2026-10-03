"""审计链看门狗（SECURITY-DEFENSE-PLAN §4.2.2，片 A2 前半）。

背景：片 A1 给 ``AuditStore.append()`` 写上了哈希链、``AuditStore.verify_chain()``
能校，但全仓零生产调用点 —— daemon 从来不校验自己的审计链。本片把校验接上：
daemon 启动即校一次，之后按 ``TRIMUM_AUDIT_VERIFY_INTERVAL``（默认 300s）定时校，
断链 / 校验失败发 ``security.audit_breach`` 事件并打告警日志。

事件口径（**本片最容易做错、验收必查**）：破链事件必须用**裸 ``publish``**
（参照 ``sec_monitor.py`` 的 ``_dispatch``），``event_type`` 精确等于
``"security.audit_breach"``。**绝不许**用 ``EventBus.emit_event()`` —— 它会自动加
``NAMESPACE_EVENT``（``"event."``）前缀，类型变成 ``event.security.audit_breach``，
而剧本触发器是精确串匹配，就永远命中不了。后人很容易顺手改成 emit_event。

已知边界的覆盖情况：① 前缀截断 ② 尾部截断 ③ 删 hmac+删锚 三条**已由带外见证
覆盖**（生成侧 ``cf7a773`` + 本片的比对）；④ 旧写者混写由 ``verify_chain()`` 覆盖。
剩下的已知边界：见证只提高门槛：能同时写 ``$TRIMUM_HOME`` 的攻击者仍可一并伪造；
真正的远程见证要第二台可信节点（暂无）。见证缺席时按「补种 + 警告」处理（有痕补齐），
因此**首次**升级到本版本时不会误报。
"""

from __future__ import annotations

import asyncio
import os
import time

from .audit_store import AuditStore
from .audit_witness import compare_witness, read_witness, record_witness, snapshot
from .event_bus import EVENT_SEC_AUDIT_BREACH
from .logger import get_logger
from .models import EventSeverity, SystemEvent

DEFAULT_INTERVAL_SECONDS = 300.0
EVENT_SOURCE = "audit-watchdog"
MAX_ERRORS_IN_EVENT = 10

log = get_logger("audit_watchdog")


def default_interval() -> float:
    """读 ``TRIMUM_AUDIT_VERIFY_INTERVAL``；空/没设/解析失败都回退默认（不抛）。"""
    raw = os.environ.get("TRIMUM_AUDIT_VERIFY_INTERVAL", "")
    if not raw.strip():
        return DEFAULT_INTERVAL_SECONDS
    try:
        return float(raw)
    except ValueError:
        log.warning("audit_watchdog.bad_interval_env", raw=raw, fallback=DEFAULT_INTERVAL_SECONDS)
        return DEFAULT_INTERVAL_SECONDS


class AuditWatchdog:
    """启动即校一次 + 定时校验；断链 / 校验抛异常都按破链发事件（fail-closed）。"""

    def __init__(self, event_bus, store: AuditStore | None = None, interval: float | None = None) -> None:
        self._bus = event_bus
        self._store = store or AuditStore()
        self.interval = default_interval() if interval is None else float(interval)

    async def verify_once(self) -> tuple[bool, list[str]]:
        """校一次链。

        ``verify_chain()`` 是同步文件 IO（``audit_store.py`` 读磁盘），**必须**
        丢到线程（``asyncio.to_thread``），不许在事件循环里直跑。

        口径：
        - 校验通过 ⇒ 记 info 日志，返回 ``(True, [])``，**不发任何事件**。
        - 校验不通过 ⇒ 记 error 日志 + 发破链事件，返回 ``(False, errors)``。
        - ``to_thread`` 本身抛异常（文件不可读 / 权限错等）⇒ **按破链处理
          （fail-closed）**：§4.2.2「hash 链断链 / 审计文件不可写」都算 breach，
          同样发事件，返回 ``(False, [f"{type(exc).__name__}: {exc}"])``。
        """
        try:
            ok, errors = await asyncio.to_thread(self._store.verify_chain)
            witness_violations = await asyncio.to_thread(self._witness_violations)
        except Exception as exc:  # noqa: BLE001 —— 校验抛异常按破链（fail-closed）
            errors = [f"{type(exc).__name__}: {exc}"]
            witness_violations = []
            ok = False
            log.error(
                "audit_watchdog.audit_chain_breach",
                path=str(self._store.path),
                error_count=len(errors) + len(witness_violations),
                error=str(exc),
                hint="人工：trm workflow run threat-audit-integrity-check",
            )
            await self._publish_breach(errors, witness_violations)
            return False, errors
        if ok and not witness_violations:
            log.info(
                "audit_watchdog.audit_chain_ok",
                path=str(self._store.path),
                interval=self.interval,
                witness="ok",
            )
            return True, []
        log.error(
            "audit_watchdog.audit_chain_breach",
            path=str(self._store.path),
            error_count=len(errors) + len(witness_violations),
            errors=errors[:5],
            witness_violations=witness_violations[:5],
            hint="人工：trm workflow run threat-audit-integrity-check",
        )
        await self._publish_breach(errors, witness_violations)
        return False, errors + [f"witness: {v}" for v in witness_violations]

    def _witness_violations(self) -> list[str]:
        """读见证 + 采当前状态 + 比对；**同步**（文件 IO，调用方丢线程）。

        口径（照做）：
        ① 见证缺席、或见证的 ``audit_path`` 不是这一份日志：
           - 当前**没有任何段**（审计文件都还没出现）⇒ 什么都不做，返回 ``[]``（没东西可比）；
           - 否则 ⇒ ``log.warning("audit_witness.absent_seeded", ...)`` 后 ``record_witness(self._store.path)``
             **补种**一份，返回 ``[]``（有痕补齐，不报 breach —— 否则在新机 / 老数据上会永久误报）。
        ② 见证在 ⇒ 返回 ``compare_witness(witness, current)``。
        ③ 本方法自身抛异常（读不出 / 采集失败）⇒ **按违规处理（fail-closed）**：
           返回 ``[f"witness check failed: {type(exc).__name__}: {exc}"]``，**不许**静默返回 ``[]``。
        ④ 同一 ``TRIMUM_HOME`` 下并存两个 ``AuditStore`` 时，见证的 ``audit_path`` 每轮都不匹配
           ⇒ 每轮都会「警告 + 补种」，等于见证失效。本方法**不**解决这个边界（要彻底解决需把 witness
           做成 per-audit-path 的命名空间）；单存储部署不触发。
        """
        try:
            witness = read_witness()
            current = snapshot(self._store.path)
            if witness is None or witness.get("audit_path") != current.get("audit_path"):
                if not current.get("segments"):
                    return []
                log.warning(
                    "audit_witness.absent_seeded",
                    audit_path=str(self._store.path),
                    reason="witness missing or audit_path mismatch",
                )
                record_witness(self._store.path)
                return []
            return compare_witness(witness, current)
        except Exception as exc:  # noqa: BLE001 —— 读不出 / 采集失败按违规处理（fail-closed）
            log.warning("audit_witness.check_failed", error=str(exc))
            return [f"witness check failed: {type(exc).__name__}: {exc}"]

    async def _publish_breach(self, errors: list[str], witness_violations: list[str] | None = None) -> None:
        """裸 publish（见模块 docstring「事件口径」；绝不用 emit_event）。"""
        violations = witness_violations or []
        await self._bus.publish(
            SystemEvent(
                event_type=EVENT_SEC_AUDIT_BREACH,  # 精确等于 "security.audit_breach"
                source=EVENT_SOURCE,
                severity=EventSeverity.CRITICAL,
                payload={
                    "audit_path": str(self._store.path),
                    "error_count": len(errors) + len(violations),
                    "errors": errors[:MAX_ERRORS_IN_EVENT],
                    "witness_violations": violations[:MAX_ERRORS_IN_EVENT],
                    "checked_at": time.time(),
                },
            )
        )

    async def run_forever(self) -> None:
        """循环校到被 cancel。

        ① **先校一次再睡**（「启动时校验」不是「等一个 interval 再校」）；
        ② ``interval <= 0`` ⇒ 只校一次就返回（0/负数 = 只跑启动那一次）；
        ③ ``CancelledError`` 必须放行（daemon 关停靠它）。
        """
        while True:
            try:
                await self.verify_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 —— 兜底：看门狗自己不能死
                log.warning("audit_watchdog.verify_crashed", error=str(exc))
            if self.interval <= 0:
                return
            await asyncio.sleep(self.interval)
