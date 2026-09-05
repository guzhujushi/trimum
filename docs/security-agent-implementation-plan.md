# Security Agent 全链路实现规格

> 制定：2026-09-05
> 目的：提供 SECURITY-DEFENSE-PLAN.md 设计落地为代码的实现蓝图
> 原则：只改现有代码结构，不重构。增量新增，最小侵入。

---

## 概览：新增文件 & 修改文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/trimum_core/sec_monitor.py` | 🆕 新建 | ThreatMatcher + 上下文追踪 + Event Bus 订阅 |
| `src/trimum_core/sec_executor.py` | 🆕 新建 | SecBlocker / SecAudit / SecNotif |
| `src/trimum_core/threat_workflows.py` | 🆕 新建 | 预注册的威胁应对 YAML 工作流（内存加载） |
| `src/trimum_core/tool_gateway.py` | 🔧 修改 | execute() 路径增加 Layer 4：SecurityRule 调用 |
| `src/trimum_core/security_rule.py` | 🔧 修改 | 增加 can_execute() 对外接口，对接 SecMonitor |
| `src/trimum_core/policy_engine.py` | 🔧 修改 | 增加 check_landlock() 接口 |
| `src/trimum_core/workflow_engine.py` | 🔧 修改 | 集成威胁工作流注册 |
| `src/trimum_core/event_bus.py` | 🔧 修改 | 注册新事件类型常量 |
| `src/trimum_core/models.py` | 🔧 修改 | 增加 ThreatMatch / SecVerdict / SecEvent 类型 |
| `src/trimum_core/__init__.py` | 🔧 修改 | 导出新模块 |
| `tests/test_security_chain.py` | 🆕 新建 | 全链路集成测试 |
| `tests/test_sec_monitor.py` | 🆕 新建 | 单元测试 |

---

## 1. Models 扩展（models.py）

### 新增枚举 / 数据类

```python
class ThreatCategory(str, Enum):
    PRIV_ESCAPE = "priv_escape"        # 权限逃逸
    MALWARE = "malware"                # 恶意软件
    DATA_THEFT = "data_theft"          # 数据窃取
    C2_BOTNET = "c2_botnet"            # C2/僵尸网络
    SUPPLY_CHAIN = "supply_chain"      # 供应链投毒
    LLM_ATTACK = "llm_attack"          # LLM 特有攻击

class DefenseAction(str, Enum):
    DENY = "deny"
    CONFIRM = "confirm"
    ALLOW = "allow"
    FREEZE = "freeze"                  # SIGSTOP 冻结
    KILL = "kill"                      # SIGKILL
    ISOLATE = "isolate"                # 网络/沙箱隔离
    WORKFLOW = "workflow"              # 触发对应工作流

class OpContext(str, Enum):
    NORMAL = "normal"
    DOWNLOAD_THEN_EXEC = "download_then_exec"
    WRITE_THEN_EXEC = "write_then_exec"
    WRITE_THEN_ENCRYPT = "write_then_encrypt"
    KEY_STEAL = "key_steal"
    SUID_STORM = "suid_storm"
    CLONE_THEN_BUILD = "clone_then_build"
    FIRST_TIME_OP = "first_time_op"
    COMPILE_THEN_EXEC = "compile_then_exec"      # 🔄 新增：gcc → 立即执行

class SecVerdict(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"
    CONFIRM = "confirm"
    FREEZE = "freeze"

class ThreatMatch(BaseModel):
    """ThreatMatcher 的输出"""
    threat_name: str
    category: ThreatCategory
    defense: DefenseAction
    confidence: float = 0.0
    matched_pattern: str = ""
    workflow_name: str = ""              # 非空则触发对应工作流
    reason: str = ""

class AuditRecord(BaseModel):
    """审计记录（已扩展 hash 链字段）"""
    timestamp: float
    event_id: str
    agent_id: str
    command: str
    threat: str
    verdict: str
    reason: str
    context: str
    sandbox: str
    layer_hit: str
    prev_hash: str = ""                  # hash 链
    hmac: str = ""                       # 签名
```

---

## 2. Event Bus 新事件类型

在 `event_bus.py` 中注册以下事件常量（用已有 `EventBus.publish` 机制）：

```python
# --- 已有事件 ---
# agent.executing / agent.executed
# security.mode_change
# workflow.threat_response

# --- 新安全事件 ---
EVENT_SEC_MONITOR = "security.monitor_result"       # SecMonitor 输出
EVENT_SEC_ALERT = "security.alert"                   # 安全告警
EVENT_SEC_BLOCKED = "security.blocked"               # 已阻断
EVENT_SEC_EBPF = "security.ebpf_alert"               # eBPF 告警
EVENT_SEC_FUSE = "security.fuse_triggered"            # 性能熔断
EVENT_SEC_AUDIT_BREACH = "security.audit_breach"      # 审计完整性破坏
EVENT_WORKFLOW_TRIGGER = "workflow.trigger"            # 触发应对工作流
```

---

## 3. SecMonitor（新建 sec_monitor.py）

### 核心职责
- 订阅 `agent.executing` 事件
- 调用 ThreatMatcher.match() → 输出 ThreatMatch
- 维护 Agent 操作上下文环缓冲区（OpContextTracker）
- 通知 SecExecutor

### 接口设计

```python
class ThreatMatcher:
    """病毒名称 → 特征 → 防御动作 映射表"""

    def match(self, agent_id: str, command: str, context: str) -> list[ThreatMatch]:
        """输入命令，返回匹配的威胁列表（按优先级排序）"""
        ...

    def match_sequence(self, agent_id: str, ops: list[dict]) -> Optional[ThreatMatch]:
        """输入操作序列，返回匹配的威胁"""
        ...

class OpContextTracker:
    """Agent 操作上下文追踪"""

    def __init__(self, maxlen: int = 20):
        self._cache: dict[str, deque] = {}   # agent_id → deque of ops

    def record(self, agent_id: str, cmd: str, file_created: str = "",
               file_modified: str = "") -> OpContext:
        """记录操作，返回当前上下文标记"""
        ...

    def get_context(self, agent_id: str) -> OpContext:
        ...

class SecMonitor:
    """安全监听器主类"""

    def __init__(self, event_bus: EventBus, threat_matcher: ThreatMatcher,
                 context_tracker: OpContextTracker, executor: "SecExecutor"):
        ...

    async def start(self):
        """订阅 Event Bus 事件"""
        self.event_bus.subscribe("agent.executing", self._on_executing)
        self.event_bus.subscribe("agent.executed", self._on_executed)
        ...

    async def _on_executing(self, event: SystemEvent) -> None:
        """agent.executing 处理器"""
        agent_id = event.payload.get("agent_id", "")
        command = event.payload.get("command", "")
        context = self.context_tracker.get_context(agent_id)

        # Step 1: ThreatMatcher.match()
        threats = self.threat_matcher.match(agent_id, command, context)
        if threats:
            await self._dispatch(threats[0], event)
            return

        # Step 2: 操作序列分析
        seq_threat = self.threat_matcher.match_sequence(
            agent_id, list(self.context_tracker._cache.get(agent_id, [])))
        if seq_threat:
            await self._dispatch(seq_threat, event)
            return

        # Step 3: 无法匹配 → 发布 security.alert 让 Security Agent 深度判断
        await self.event_bus.publish(SystemEvent(
            type="security.alert",
            severity=EventSeverity.INFO,
            source="sec_monitor",
            payload={"agent_id": agent_id, "command": command,
                     "reason": "no_threat_match", "needs_llm": True}
        ))

    async def _dispatch(self, threat: ThreatMatch, event: SystemEvent) -> None:
        """执行防御动作"""
        # 发布 security.monitor_result
        await self.event_bus.publish(SystemEvent(
            type="security.monitor_result",
            severity=EventSeverity.WARNING,
            source="sec_monitor",
            payload={"threat": threat.dict(), "original_event": event.dict()}
        ))

        # 调用 SecExecutor
        await self.executor.execute(threat, event)
```

---

## 4. SecExecutor（新建 sec_executor.py）

### 4.1 SecBlocker

```python
class SecBlocker:
    """阻断器"""

    @staticmethod
    async def deny(pid: int = 0, reason: str = "") -> None:
        """DENY — 由 PolicyEngine 在 execute() 入口阻止，不执行"""
        # 实际 DENY 在 ToolGateway.execute() 中；这里只做日志和通知
        pass

    @staticmethod
    async def freeze(pid: int) -> bool:
        """SIGSTOP 冻结进程（勒索/挖矿进行中）"""
        try:
            os.kill(pid, signal.SIGSTOP)
            return True
        except ProcessLookupError:
            return False

    @staticmethod
    async def kill(pid: int) -> bool:
        """SIGKILL 杀进程（后门/rootkit 确认）"""
        try:
            os.kill(pid, signal.SIGKILL)
            return True
        except ProcessLookupError:
            return False

    @staticmethod
    async def isolate_network(pid: int) -> None:
        """临时网络隔离（iptables REJECT，Phase 4 实现）"""
        # Phase 4: iptables -A OUTPUT -p tcp --dport 443 -m owner --pid-owner {pid} -j REJECT
        pass
```

### 4.2 SecAudit

```python
class SecAudit:
    """审计器（含 hash 链完整性）"""

    def __init__(self, audit_path: str = "~/.trimum/audit/security.log",
                 hmac_key: str = ""):   # HMAC 密钥从 .env 读取
        self.audit_path = Path(audit_path).expanduser()
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self.hmac_key = hmac_key or "default-dev-key"

    def _read_last_hash(self) -> str:
        """读最后一条记录的 hash"""
        if not self.audit_path.exists():
            return ""
        # 读最后一行 JSON，取 prev_hash 字段
        ...

    def _compute_hmac(self, record: dict) -> str:
        """HMAC-SHA256 签名"""
        import hmac, hashlib, json
        data = json.dumps(record, sort_keys=True, default=str)
        return hmac.new(
            self.hmac_key.encode(), data.encode(), hashlib.sha256
        ).hexdigest()

    async def log(self, record: AuditRecord) -> None:
        """写入审计记录 + hash 链"""
        prev_hash = self._read_last_hash()
        record.prev_hash = prev_hash

        dict_record = record.dict()
        dict_record["hmac"] = self._compute_hmac(dict_record)

        with open(self.audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(dict_record, default=str) + "\n")

    def verify_chain(self) -> tuple[bool, list[str]]:
        """验证整个审计日志的 hash 链完整性"""
        # 逐行读取，验证 prev_hash 连续 + HMAC 签名
        errors = []
        prev = ""
        with open(self.audit_path, "r") as f:
            for line in f:
                rec = json.loads(line)
                if rec["prev_hash"] != prev:
                    errors.append(f"Hash chain broken at {rec['event_id']}")
                expected_hmac = self._compute_hmac(
                    {k: v for k, v in rec.items() if k != "hmac"}
                )
                if rec["hmac"] != expected_hmac:
                    errors.append(f"HMAC mismatch at {rec['event_id']}")
                prev = hashlib.sha256(line.encode()).hexdigest()
        return len(errors) == 0, errors
```

### 4.3 SecNotif

```python
class SecNotif:
    """通知器"""

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus

    async def alert(self, threat: ThreatMatch, event: SystemEvent) -> None:
        """发布 security.alert"""
        await self.event_bus.publish(SystemEvent(
            type="security.alert",
            severity=EventSeverity.WARNING,
            source="sec_executor",
            payload={
                "threat_name": threat.threat_name,
                "defense": threat.defense.value,
                "agent_id": event.payload.get("agent_id", ""),
                "command": event.payload.get("command", ""),
                "reason": threat.reason,
            }
        ))

    async def blocked(self, threat: ThreatMatch, event: SystemEvent) -> None:
        """发布 security.blocked"""
        await self.event_bus.publish(SystemEvent(
            type="security.blocked",
            severity=EventSeverity.HIGH,
            source="sec_executor",
            payload={
                "threat_name": threat.threat_name,
                "agent_id": event.payload.get("agent_id", ""),
                "command": event.payload.get("command", ""),
                "reason": threat.reason,
            }
        ))
```

### 4.4 SecExecutor 主类

```python
class SecExecutor:
    """安全执行器主类"""

    def __init__(self, event_bus: EventBus, audit: SecAudit, notif: SecNotif):
        self.blocker = SecBlocker()
        self.audit = audit
        self.notif = notif
        self.event_bus = event_bus

    async def execute(self, threat: ThreatMatch, event: SystemEvent) -> None:
        """执行最高优先级的防御动作"""
        agent_id = event.payload.get("agent_id", "")
        command = event.payload.get("command", "")
        pid = event.payload.get("pid", 0)

        # 记录审计
        audit_record = AuditRecord(
            timestamp=time.time(),
            event_id=f"sec_{uuid4().hex[:8]}",
            agent_id=agent_id,
            command=command,
            threat=threat.threat_name,
            verdict=threat.defense.value,
            reason=threat.reason,
            context=event.payload.get("context", "normal"),
            sandbox=event.payload.get("sandbox", "default"),
            layer_hit=event.payload.get("layer_hit", "L2"),
        )
        await self.audit.log(audit_record)

        # 执行阻断
        if threat.defense == DefenseAction.DENY:
            await self.notif.blocked(threat, event)
            # 实际 DENY 由 ToolGateway.execute() 处理

        elif threat.defense == DefenseAction.FREEZE:
            await self.blocker.freeze(pid)
            await self.notif.alert(threat, event)

        elif threat.defense == DefenseAction.KILL:
            await self.blocker.kill(pid)
            await self.notif.blocked(threat, event)

        elif threat.defense == DefenseAction.ISOLATE:
            await self.blocker.isolate_network(pid)
            await self.notif.alert(threat, event)

        # 触发应对工作流
        if threat.workflow_name:
            await self.event_bus.publish(SystemEvent(
                type="workflow.trigger",
                severity=EventSeverity.INFO,
                source="sec_executor",
                payload={
                    "workflow_name": threat.workflow_name,
                    "threat_name": threat.threat_name,
                    "agent_id": agent_id,
                }
            ))
```

---

## 5. ToolGateway 修改（tool_gateway.py）

### 新增 Layer 4

```python
class ToolGateway:
    def __init__(self, ...):
        # 新增
        self.sec_monitor: Optional[SecMonitor] = None
        self.sec_executor: Optional[SecExecutor] = None
        self.op_context: OpContextTracker = OpContextTracker()

    async def execute(self, request: ExecuteRequest) -> ExecuteResponse:
        # 已有 Layer 0-3 ...
        # ...

        # === LAYER 4: Security Monitor ===
        if self.sec_monitor:
            context = self.op_context.get_context(request.source_type)
            threats = self.sec_monitor.threat_matcher.match(
                request.source_type, cmd_str, context
            )
            if threats:
                top_threat = threats[0]
                if top_threat.defense in (DefenseAction.DENY, DefenseAction.CONFIRM):
                    # 记录操作序列
                    self.op_context.record(request.source_type, cmd_str)

                    await self.sec_executor.execute(top_threat, SystemEvent(
                        type="agent.executing",
                        severity=EventSeverity.WARNING,
                        source="tool_gateway",
                        payload={
                            "agent_id": request.source_type,
                            "command": cmd_str,
                            "pid": os.getpid(),
                        }
                    ))
                    if top_threat.defense == DefenseAction.DENY:
                        return ExecuteResponse(
                            success=False,
                            stdout="",
                            stderr=f"[SECURITY BLOCKED] {top_threat.reason}",
                            exit_code=137,
                        )

        # 记录操作序列（无论是否匹配威胁）
        self.op_context.record(request.source_type, cmd_str)

        # ===== 继续现有 execute 流程 =====
```

---

## 6. SecurityRule 修改（security_rule.py）

```python
class SecurityRule:
    async def can_execute(self, request, policy_result=None):
        """全链路入口
        返回：(Action, reason)
        """
        if policy_result is None:
            _, action, reason = self.policy_engine.evaluate(
                ExecuteRequest(command=request.command, source_type=request.source_type)
            )
        else:
            _, action, reason = policy_result
        if action == Action.DENY:
            return (Action.DENY, reason)
        if not await self._check_rate_limit(request):
            return (Action.DENY, "Rate limit exceeded")
        return (Action.ALLOW, "")

    async def _check_rate_limit(self, request):
        if not self.behavior_monitor:
            return True
        rate_ok, _ = self.behavior_monitor.check_command(
            request.source_type, request.command
        )
        return rate_ok
```

---

## 7. PolicyEngine 修改

```python
class PolicyEngine:
    def check_landlock(self, path: str, access_type: str) -> bool:
        """预留接口。Phase 4 实现，当前返回 True"""
        return True
```

---

## 8. 威胁工作流注册（threat_workflows.py）

```python
THREAT_WORKFLOWS = [
    {
        "name": "threat-prelink-check",
        "trigger": "security.monitor_result",
        "filter": {"threat_name": "ld_preload"},
        "steps": ["cat /etc/ld.so.preload", "ls -la /etc/ld.so.preload",
                  "sha256sum /etc/ld.so.preload", "report"],
    },
    {
        "name": "threat-ebpf-scan",
        "trigger": "security.monitor_result",
        "filter": {"threat_name": "ebpf_hijack"},
        "steps": ["ls /sys/fs/bpf/", "bpftool prog list (mock)",
                  "find /lib/modules/ -mmin -10", "report"],
    },
    {
        "name": "threat-persistence-sweep",
        "trigger": "security.monitor_result",
        "filter": {"threat_name": "persistence"},
        "steps": [
            "ld.so.preload", "crontab", "systemd", "init.d",
            ".bashrc", "XDG autostart", "一次性清理全部", "确认无残留",
        ],
    },
    {
        "name": "threat-audit-integrity-check",
        "trigger": "cron",
        "steps": ["verify_hash_chain", "verify_hmac", "report"],
    },
    {
        "name": "threat-prompt-injection-check",
        "trigger": "security.monitor_result",
        "filter": {"threat_name": "prompt_injection"},
        "steps": ["check_injection_patterns", "check_trust_score",
                  "check_cmd_params", "audit"],
    },
]
```

---

## 9. 初始化链路（main.py）

```python
from trimum_core.sec_monitor import SecMonitor, ThreatMatcher, OpContextTracker
from trimum_core.sec_executor import SecExecutor, SecAudit, SecNotif
from trimum_core.threat_workflows import THREAT_WORKFLOWS

# 初始化
sec_audit = SecAudit(audit_path="~/.trimum/audit/security.log")
sec_notif = SecNotif(event_bus)
sec_executor = SecExecutor(event_bus, sec_audit, sec_notif)
threat_matcher = ThreatMatcher()
context_tracker = OpContextTracker(maxlen=20)

sec_monitor = SecMonitor(event_bus, threat_matcher, context_tracker, sec_executor)
await sec_monitor.start()

# 挂载到 ToolGateway
tool_gateway.sec_monitor = sec_monitor
tool_gateway.sec_executor = sec_executor
tool_gateway.op_context = context_tracker

# 注册威胁工作流
for wf in THREAT_WORKFLOWS:
    workflow_engine.register_tarl_workflow(wf["name"], wf["trigger"], ...)
```

---

## 10. 实现顺序 & 预估工时

| 步骤 | 内容 | 依赖 | 预估 |
|------|------|------|------|
| 1 | models.py 新增类型 | 无 | 15min |
| 2 | sec_monitor.py (ThreatMatcher + OpContextTracker) | 1 | 30min |
| 3 | sec_executor.py (SecAudit/SecBlocker/SecNotif) | 1 | 30min |
| 4 | SecMonitor 主类 + Event Bus 对接 | 2,3 | 20min |
| 5 | threat_workflows.py | 无 | 10min |
| 6 | ToolGateway Layer 4 集成 | 4 | 15min |
| 7 | SecurityRule.can_execute() 封装 | 4 | 10min |
| 8 | main.py 初始化链路 | 4,5,6,7 | 10min |
| 9 | 单元测试 | 2,3,4 | 20min |
| 10 | 集成测试 | 8 | 20min |
| | **合计** | | **~3h** |