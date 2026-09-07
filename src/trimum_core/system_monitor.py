"""System Monitor — 硬件状态监听 + Event Bus 通知。

职责：
1. 定期采集 CPU/GPU/Disk/RAM 状态
2. 超过阈值时发布异常事件到 Event Bus
3. 提供查询接口供其他组件使用

设计成 Tool Gateway 中的内置工具，不独立成 Agent。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

try:
    import psutil
except ImportError:
    psutil = None  # type: ignore

log = logging.getLogger("trimum_core.system_monitor")


class SystemMonitor:
    """硬件状态监听与异常检测。

    作为 Tool Gateway 的内置工具运行，定时采集系统指标，
    异常时通过回调发布事件到 Event Bus。

    Usage::

        monitor = SystemMonitor()
        monitor.set_event_callback(lambda event_type, payload: event_bus.emit(...))
        await monitor.collect()  # 单次采集
        await monitor.start_collecting(interval=30)  # 定时采集
    """

    def __init__(self) -> None:
        self._callback: Optional[callable] = None
        self._running = False
        self._thresholds: dict[str, float] = {
            "cpu_percent": 80.0,       # CPU 使用率 > 80%
            "memory_percent": 85.0,     # 内存使用率 > 85%
            "disk_percent": 90.0,       # 磁盘使用率 > 90%
            "load_5min": 4.0,           # 5 分钟负载 > 4.0
        }
        self._last_alert: dict[str, float] = {}  # 去重：同类型告警间隔
        self._alert_cooldown: float = 60.0  # 秒

    # ------------------------------------------------------------------
    # 回调设置
    # ------------------------------------------------------------------

    def set_event_callback(self, callback: callable) -> None:
        """设置事件回调函数。

        callback(event_type: str, payload: dict) -> None
        回调会收到 event_type = "system.alert" 的事件。
        """
        self._callback = callback

    # ------------------------------------------------------------------
    # 阈值管理
    # ------------------------------------------------------------------

    def set_threshold(self, name: str, value: float) -> None:
        """动态调整某个指标的阈值."""
        if name in self._thresholds:
            self._thresholds[name] = value

    def get_thresholds(self) -> dict[str, float]:
        """获取当前所有阈值."""
        return dict(self._thresholds)

    # ------------------------------------------------------------------
    # 单次采集
    # ------------------------------------------------------------------

    async def collect(self) -> dict[str, Any]:
        """采集一次系统状态并返回完整报告。

        Returns: {
            "cpu": {"percent": ..., "count": ..., "load_1m": ..., ...},
            "memory": {"total_gb": ..., "used_gb": ..., "percent": ...},
            "disk": {"/": {"total_gb": ..., "used_gb": ..., "percent": ...}, ...},
            "network": {"bytes_sent_mb": ..., "bytes_recv_mb": ...},
            "alerts": [...],
        }
        """
        if psutil is None:
            return {"error": "psutil not installed"}

        report: dict[str, Any] = {"timestamp": time.time()}
        alerts: list[dict] = []

        # CPU
        cpu_percent = psutil.cpu_percent(interval=0.5)
        cpu_count = psutil.cpu_count()
        load_1m, load_5m, load_15m = (psutil.getloadavg() if hasattr(psutil, 'getloadavg') else (0, 0, 0))
        report["cpu"] = {
            "percent": cpu_percent,
            "count": cpu_count,
            "load_1m": load_1m,
            "load_5m": load_5m,
            "load_15m": load_15m,
        }

        # CPU 告警
        if cpu_percent > self._thresholds["cpu_percent"]:
            alert = self._make_alert("cpu_high", cpu_percent, self._thresholds["cpu_percent"])
            if alert:
                alerts.append(alert)

        if load_5m > self._thresholds["load_5min"]:
            alert = self._make_alert("load_high", load_5m, self._thresholds["load_5min"])
            if alert:
                alerts.append(alert)

        # Memory
        mem = psutil.virtual_memory()
        mem_total_gb = mem.total / (1024 ** 3)
        mem_used_gb = mem.used / (1024 ** 3)
        report["memory"] = {
            "total_gb": round(mem_total_gb, 1),
            "used_gb": round(mem_used_gb, 1),
            "available_gb": round(mem.available / (1024 ** 3), 1),
            "percent": mem.percent,
        }

        if mem.percent > self._thresholds["memory_percent"]:
            alert = self._make_alert("memory_high", mem.percent, self._thresholds["memory_percent"])
            if alert:
                alerts.append(alert)

        # Disk
        report["disk"] = {}
        for part in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(part.mountpoint)
                total_gb = usage.total / (1024 ** 3)
                used_gb = usage.used / (1024 ** 3)
                report["disk"][part.mountpoint] = {
                    "total_gb": round(total_gb, 1),
                    "used_gb": round(used_gb, 1),
                    "free_gb": round(usage.free / (1024 ** 3), 1),
                    "percent": usage.percent,
                    "fstype": part.fstype,
                }
                if usage.percent > self._thresholds["disk_percent"]:
                    alert = self._make_alert("disk_high", usage.percent, self._thresholds["disk_percent"])
                    if alert:
                        alert["mountpoint"] = part.mountpoint
                        alerts.append(alert)
            except (PermissionError, OSError):
                continue

        # Network (累计)
        net = psutil.net_io_counters()
        report["network"] = {
            "bytes_sent_mb": round(net.bytes_sent / (1024 ** 2), 1),
            "bytes_recv_mb": round(net.bytes_recv / (1024 ** 2), 1),
            "packets_sent": net.packets_sent,
            "packets_recv": net.packets_recv,
        }

        report["alerts"] = alerts

        # 有告警 → 发布到 Event Bus
        for alert in alerts:
            if self._callback:
                self._callback("system.alert", alert)

        return report

    # ------------------------------------------------------------------
    # 定时采集
    # ------------------------------------------------------------------

    async def start_collecting(self, interval: float = 30.0) -> None:
        """启动定时采集循环（协程，需要 await 或 create_task）。

        Args:
            interval: 采集间隔（秒），默认 30 秒
        """
        self._running = True
        while self._running:
            try:
                await self.collect()
            except Exception as e:
                log.warning("System monitor collect error: %s", e)
            await asyncio.sleep(interval)

    def stop_collecting(self) -> None:
        """停止定时采集循环."""
        self._running = False

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------

    async def get_summary(self) -> dict[str, Any]:
        """获取简洁的系统状态摘要（不含告警，轻量）。"""
        if psutil is None:
            return {"status": "psutil_not_installed"}
        return {
            "cpu_percent": round(psutil.cpu_percent(interval=0.1), 1),
            "memory_percent": round(psutil.virtual_memory().percent, 1),
            "uptime_days": round((time.time() - psutil.boot_time()) / 86400, 1),
        }

    async def is_healthy(self) -> tuple[bool, list[str]]:
        """快速健康检查。返回 (healthy, [issues])。"""
        if psutil is None:
            return False, ["psutil not installed"]
        issues = []
        report = await self.collect()
        for alert in report.get("alerts", []):
            issues.append(f"{alert['type']}: {alert['value']:.1f} > {alert['threshold']:.1f}")
        return len(issues) == 0, issues

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _make_alert(
        self,
        alert_type: str,
        value: float,
        threshold: float,
    ) -> dict | None:
        """生成告警事件（带冷却去重）。"""
        now = time.time()
        last = self._last_alert.get(alert_type, 0)
        if now - last < self._alert_cooldown:
            return None
        self._last_alert[alert_type] = now
        return {
            "type": alert_type,
            "value": round(value, 1),
            "threshold": threshold,
            "timestamp": now,
        }


# 顶部需要引入 asyncio
import asyncio  # noqa: E402
