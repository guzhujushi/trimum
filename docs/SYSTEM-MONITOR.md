# System Monitor

> **架构归属（2026-11-11 重构）**：本文是 **System Intelligence Observation** 的早期采集器说明，
> 不是完整的 Workload Analysis Engine。总体架构见 `docs/ARCH.md` §4，
> 详细设计见 `docs/architecture/system-intelligence.md`。
>
> 最后更新：2026-11-11（归属标注 + 修正 EventBus 示例）；机制内容沿用 2026-09-01 版本。
> 硬件状态监听 + Event Bus 通知，作为 Tool Gateway 内置工具运行

---

## 职责

1. **定时采集** CPU/Disk/RAM 状态（GPU 采集尚未实现）
2. **阈值告警** — 超过阈值时通过 Event Bus 发布 `system.alert`
3. **查询接口** — 供其他组件（Security Agent、CLI、API）获取当前状态
4. **健康检查** — 快速判断系统是否正常

## 采集指标

| 类别 | 指标 | 阈值（默认） |
|---|---|---|
| CPU | percent, count, load_1m/5m/15m | cpu_percent > 80%, load_5min > 4.0 |
| Memory | total_gb, used_gb, available_gb, percent | memory_percent > 85% |
| Disk | total_gb, used_gb, free_gb, percent, fstype | disk_percent > 90% |
| Network | bytes_sent/recv_mb, packets_sent/recv | 无告警（仅记录） |

## 告警事件格式

```json
{
  "type": "system.alert",
  "payload": {
    "type": "cpu_high",        // alert 类型
    "value": 92.5,             // 当前值
    "threshold": 80.0,         // 阈值
    "timestamp": 1693567200.0  // 时间戳
  }
}
```

### 告警类型

| alert_type | 含义 |
|---|---|
| `cpu_high` | CPU 使用率超过阈值 |
| `load_high` | 5 分钟负载超过阈值 |
| `memory_high` | 内存使用率超过阈值 |
| `disk_high` | 磁盘使用率超过阈值（含 mountpoint） |

> 每种告警有 60 秒冷却时间，避免告警风暴。

## 使用方式

### 作为工具注册

```python
from trimum_core.system_monitor import SystemMonitor

# 传入 EventBus 后，采集结果与告警由 SystemMonitor 内部 publish。
monitor = SystemMonitor(event_bus=event_bus)

# 可选：额外回调（同步函数），用于打印 / 转发；不要在这里调用不存在的 event_bus.emit()。
monitor.set_event_callback(lambda event_type, payload: print(event_type, payload))

# 单次采集
report = await monitor.collect()

# 定时采集（协程）
asyncio.create_task(monitor.start_collecting(interval=30))

# 健康检查
healthy, issues = await monitor.is_healthy()

# 摘要
summary = await monitor.get_summary()
```

### 动态调整阈值

```python
monitor.set_threshold("cpu_percent", 90.0)  # 放宽 CPU 告警
all_thresholds = monitor.get_thresholds()
```
