# Security Agent AGENTS.md

> 安全守门人。不信任任何输入，用规则 + 行为分析 + 弹性沙箱三层防线拦截恶意操作。
> 隶属 trimum 项目，独立于 Policy Engine 存在——Policy Engine 管"合不合规"，Security Agent 管"危不危险"。

---

## 1. 使命

拦截以下五大类威胁在 trimum 环境中的实施：

| 威胁域 | 防御重心 | 对应检测层 |
|---------|----------|-----------|
| 🎯 **权限逃逸 / 提权** | 阻止无授权的 root 操作、Docker 逃逸、系统调用滥用 | PolicyEngine + SecurityRule.can_execute() |
| 🦠 **恶意软件植入与执行** | 拦截未知二进制下载、内存执行、LD_PRELOAD 劫持 | BehaviorMonitor 异常检测 + 规则匹配 |
| 🔒 **数据窃取与勒索** | 阻断批量文件加密、大规模外传、凭证窃取 | 频率检测 + 路径白名单 + 凭据脱敏 |
| 🌐 **C2 通信 / 僵尸网络** | 检测异常出站连接、DNS 隧道特征、P2P 信令 | 网络请求频率 + 跨沙箱阻断 |
| 📦 **供应链投毒** | 审计外部依赖下载、阻止未知包管理器滥用 | PolicyEngine + 资源配额 |

---

## 2. 被拦截的威胁清单（含检测策略）

### 2.1 权限逃逸与提权

| 攻击手段 | 特征 | 拦截策略 |
|----------|------|---------|
| **LD_PRELOAD rootkit** | `LD_PRELOAD=...` 环境变量、`.so` 注入 | PolicyEngine 规则匹配 `LD_PRELOAD` 模式 → DENY |
| **内核模块加载** | `insmod`、`modprobe` | 命令黑名单 → DENY |
| **eBPF 注入** | `bpftool`、`bpftrace`、`/sys/fs/bpf` 写入 | 命令黑名单 + 路径白名单 |
| **系统调用挂钩** | `ptrace` 到其他进程、`/proc/.../mem` 写入 | 跨进程操作 → CONFIRM |
| **PAM 后门注入** | 修改 `/etc/pam.d/`、写入 PAM 模块 `.so` | 路径白名单（拒绝写 `/etc/pam.d/`） |
| **SUID/Capabilities 滥用** | `chmod +s`、`setcap`、`capsh` | 命令黑名单 → DENY |
| **Docker 逃逸** | `--privileged`、挂载 `/var/run/docker.sock` | 防溢出检测 + 沙箱配置审计 |
| **容器→宿主机逃逸** | `--pid=host`、`nsenter`、`chroot` 逃出 | SecurityRule 跨沙箱 deny 规则 |

**PolicyEngine 规则示例（policy.yaml）：**
```yaml
patterns:
  - pattern: "LD_PRELOAD"
    risk: critical
    action: deny
  - pattern: "insmod|modprobe"
    risk: critical
    action: deny
  - pattern: "bpftool|bpftrace"
    risk: high
    action: deny
  - pattern: "chmod \\+s"
    risk: high
    action: deny
  - pattern: "setcap"
    risk: high
    action: confirm
  - pattern: "nsenter|chroot"
    risk: high
    action: deny
```

### 2.2 恶意软件植入与无文件执行

| 攻击手段 | 特征 | 拦截策略 |
|----------|------|---------|
| **内存加载执行（无文件）** | `memfd_create`、`/dev/shm/*` 写入后执行 | BehaviorMonitor 文件写入→执行序列检测 |
| **curl|bash 远程加载** | `curl ... | bash`、`wget -qO- | sh` | PolicyEngine 管道匹配 → DENY |
| **Python base64 解码执行** | `python -c "import base64; exec(...)"` | 规则匹配 base64/encoded 负载模式 |
| **LD_PRELOAD 进程隐藏** | `LD_PRELOAD` hook `open()`/`readdir()` | 规则匹配 + BehaviorMonitor 分类 |
| **Cron 持久化** | `crontab -e`、写入 `/etc/cron.*` | 路径白名单（默认不允许写系统 cron） |
| **Systemd 服务持久化** | `systemctl enable`、写 `/etc/systemd/system/` | PolicyEngine 规则 + 路径白名单 |
| **挖矿二进制下载** | 从未知 IP/域名下载 ELF 后 `chmod +x && ./` | 网络请求频率检测 + 管道下载拦截 |
| **WebShell 上传** | PHP/Python 一句话木马写入 Web 目录 | 文件写入路径白名单 + 内容模式检测 |

**PolicyEngine 规则示例：**
```yaml
patterns:
  - pattern: "curl \\S+ \\| (bash|sh)"
    risk: critical
    action: deny
  - pattern: "wget \\S+ -O- \\| (bash|sh)"
    risk: critical
    action: deny
  - pattern: "python -c.*(base64|b64decode|exec\\()"
    risk: high
    action: deny
  - pattern: "crontab"
    risk: high
    action: confirm
  - pattern: "systemctl enable"
    risk: high
    action: confirm
  - pattern: "chmod \\+x .+\\.(elf|so)"
    risk: high
    action: confirm
```

### 2.3 数据窃取与勒索

| 攻击手段 | 特征 | 拦截策略 |
|----------|------|---------|
| **批量文件加密** | 遍历目录 + 大量 write() + rename() → .encrypted | BehaviorMonitor 文件写入风暴（>30次/分钟）→ DENY |
| **批量文件外传** | tar + curl/scp 到外部 IP | 网络请求 + 远程操作频率检测 |
| **SSH 密钥窃取** | 读取 ~/.ssh/id_*、authorized_keys | 路径白名单 + Agent 权限声明 |
| **环境变量/凭证窃取** | env、export、cat .env | ToolGateway 凭据脱敏 + 敏感命令审计 |
| **数据库导出** | mysqldump、pg_dump、sqlite3 .dump→外部 | 命令白名单 + 输出路径检查 |
| **勒索信创建** | 大量 README_TO_DECRYPT.txt 类文件同时出现 | 文件名模式匹配 + 内容分析（LLM 智能模式） |

**PolicyEngine 规则示例：**
```yaml
patterns:
  - pattern: "\\$\\(cat ~/\\.ssh/id"
    risk: critical
    action: deny
  - pattern: "mysqldump|pg_dump"
    risk: high
    action: confirm
  - pattern: "scp -r"
    risk: high
    action: confirm
  - pattern: "tar -czf.*\\|.*(curl|scp)"
    risk: critical
    action: deny
```

### 2.4 C2 通信 / 僵尸网络

| 攻击手段 | 特征 | 拦截策略 |
|----------|------|---------|
| **DNS 隧道** | 异常 DNS 请求次数 + 域名字段含编码数据 | BehaviorMonitor 网络请求暴增 + 域名格式异常 |
| **Telegram/WebSocket C2** | 频繁轮询 Telegram API / WebSocket 连接 | 网络请求频率 > 20 次/分钟 → 标记 |
| **P2P 中继节点** | 同时发起大量出站连接 + 监听入站端口 | Process/网络行为模式 + 资源配额 |
| **反向 Shell** | `bash -i >& /dev/tcp/...` | PolicyEngine 规则匹配 → DENY |
| **ICMP/DNS 数据隐写** | 向特定 IP 发 ping 数据包含 payload | Phase 4 网络层检测 |
| **Tor/代理出口** | 启动 tor 客户端、搭建 socks 代理 | 命令黑名单 → DENY |
| **信标心跳** | 固定间隔的 HTTP(S) 请求到冷门域名 | BehaviorMonitor 定时模式检测（Phase 4） |

**PolicyEngine 规则示例：**
```yaml
patterns:
  - pattern: "bash -i >& /dev/tcp"
    risk: critical
    action: deny
  - pattern: "mkfifo.*nc.*/bin/(bash|sh)"
    risk: critical
    action: deny
  - pattern: "tor"
    risk: high
    action: deny
  - pattern: "socat"
    risk: high
    action: confirm
  - pattern: "nc -e /bin/(bash|sh)"
    risk: critical
    action: deny
```

### 2.5 供应链投毒

| 攻击手段 | 特征 | 拦截策略 |
|----------|------|---------|
| **pip install 恶意包** | `pip install --no-deps`、typosquatting 包名 | PolicyEngine 规则 + 包的 hash 校验（Phase 4） |
| **npm/yarn install 投毒** | 大量依赖下载、postinstall 脚本执行 | 资源配额 + 网络请求频率 |
| **git clone 后门仓库** | 克隆后自动执行 git hook、make 时触发恶意代码 | Phase 4 git hook 审计 |

**PolicyEngine 规则示例：**
```yaml
patterns:
  - pattern: "pip install.*--no-deps"
    risk: high
    action: confirm
  - pattern: "npm install.*(--unsafe-perm|--ignore-scripts)"
    risk: high
    action: deny
  - pattern: "\\| bash$"
    risk: high
    action: deny
```

---

## 3. 检测维度总览

Security Agent 的每条检测逻辑走以下三层层级：

```
输入（命令 / TARL / 跨 Agent 访问）
  │
  ├─ L1: PolicyEngine 规则匹配
  │   ├── 正则匹敌模式 → risk+action 判定
  │   └── 来源感知（AI/human/workflow 不同策略）
  │
  ├─ L2: BehaviorMonitor 行为基线
  │   ├── 频率检测（写入风暴/删除风暴/网络请求风暴）
  │   ├── 新操作类型检测
  │   ├── 跨沙箱操作检测
  │   └── 操作序列异常（下载→执行、写入→重命名）
  │
  └─ L3: 资源 & 沙箱边界
      ├── CPU/内存阈值
      ├── cwd Jail（工作目录逃逸）
      └── 防溢出配置审计
```

**决策合流：**

| 三层结果 | 硬性模式 | 弹性模式 | 智能模式 |
|----------|----------|----------|----------|
| 三层全通过 | ✅ ALLOW | ✅ ALLOW | ✅ ALLOW |
| L1 拦截 | ❌ DENY | ❌ DENY | ❌ DENY |
| L2 异常（非致命） | ✅ ALLOW | ⚠️ CONFIRM | ⚠️ LLM 兜底 |
| L2 异常（致命） | ❌ DENY | ❌ DENY | ❌ DENY |
| L3 越界 | ❌ DENY | ❌ DENY | ❌ DENY |

---

## 4. 智能模式（LLM 兜底分析）

当 L1 规则未命中且 L2 BehaviorMonitor 标记可疑时触发：

```
L1 未命中 → 不确定
L2 → "suspicious"
  └→ LLM 分析（仅智能模式）
     ├── 上下文：最近 5 条操作 + 当前命令 + Agent 能力
     ├── 判断：
     │   ├── 符合能力 → allow + 记录
     │   ├── 不符但对环境无害 → allow + 记录
     │   └── 明显恶意/提权 → deny + 记录
     └── LLM 不可用 → fallback confirm（弹窗）
```

**调用限制**：
- 仅智能模式、仅 L1 未命中且 L2 可疑时触发
- 不可每请求调用（BehaviorMonitor 预过滤）
- LLM 不可用（校内断网），回退弹性模式默认策略

---

## 5. 已被 L1 硬性拦截的高危模式一览

```
LD_PRELOAD 注入                              → DENY
内核模块加载（insmod/modprobe）               → DENY
eBPF 注入（bpftool/bpftrace）                → DENY
反向 shell（bash -i /dev/tcp）               → DENY
远程加载执行（curl|bash, wget|sh）            → DENY
编码负载执行（python -c base64/exec）         → DENY
nsenter/chroot 逃逸                         → DENY
SUID 滥用（chmod +s）                        → DENY
管道后门（mkfifo + nc）                      → DENY
勒索批量重命名                               → DENY
敏感路径写入（/etc/pam.d, /etc/cron.*）      → DENY
非授权包管理器                                → DENY
```

---

## 6. 集成链路

```
AgentRegistry 注册
  └→ agent_cert.check_agent_trust() → 证书校验
     └→ 注册到 registry
        └→ Agent 执行工具
           └→ ToolGateway.execute()
              ├→ PolicyEngine.evaluate()          # L1
              ├→ _check_agent_permissions()       # L1.5
              ├→ _check_cwd_jail()                # L3
              ├→ _check_jit_auth()                # L3
              └→ SecurityRule.can_execute()       # L2+L3
                 ├→ BehaviorMonitor              # 频率/序列/跨沙箱
                 └→ 资源阈值检查
```

**当前集成状态**：
- ✅ `security_rule.py` 已实现（can_execute/can_access/can_execute_tarl）
- ✅ ToolGateway 四层检查已预留 SecurityRule 接口
- 🔄 #9 将 SecurityRule 挂到 ToolGateway 实际调用路径
- 🔄 #11 PolicyEngine LLM 升级（智能模式入口）

---

## 7. 测试策略

| 类型 | 覆盖 |
|------|------|
| 单元测试 | 每个 L1 规则的正确匹配/不匹配 |
| 单元测试 | BehaviorMonitor 频率阈值 |
| 单元测试 | SecurityRule 三层决策组合 |
| 集成测试 | 真实 curl|bash 类命令全链路拦截 |
| 集成测试 | 跨沙箱访问 allow/deny/confirm |
| 金丝雀测试 | 模拟已知 CVE payload → 确认拦截 |
