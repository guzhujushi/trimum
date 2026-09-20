# MCP 接入方案 — awesome-mcp-servers 引入准备

> 日期：2026-09-20
> 数据来源：`punkpeye/awesome-mcp-servers`（经 7993 代理抓取，原始件在 `tmp/research/awesome-README.md`）
> 结论先行：引入 awesome-mcp-servers 的第一步不是「抄列表」，而是实现 MCP 客户端 + 文件化 server 注册 + 权限接入。
> **2026-09-20 更新**：M0（设计冻结）/ M1（stdio 客户端）/ M2（注册 + 分发 + 审计）/ M3（策展导入器）
> / M4（HTTP/SSE 传输 + 空闲回收 + cgroup 绑定 + 常驻池 + 运维文档）**均已落地**，
> 代码见 `src/trimum_core/mcp_client.py` / `mcp_registry.py` / `tool_dispatchers.MCPDispatcher`
> / `api_server.py`（daemon 接线）与 `cli/commands/mcp.py`（status / restart）。
> 仍未做：③ 远端工具聚合进 `ToolRegistry`（见 §2.2 与 §6.1）。

## 1. 目标与范围

- 目标：让 trimum 能像用内置工具一样调用 MCP server 暴露的工具，且**全部调用受 Tool Gateway 管辖**。
- 范围：MCP 客户端（stdio / HTTP）、server 定义文件化、工具聚合、鉴权与审计、策展目录。
- 非目标：不把 awesome-mcp-servers 的 4,117 个条目全量引入；不做 MCP server 的托管与市场分发。
- 生态定位：MCP 是四层生态战略中的「服务层」，见 docs/ECOSYSTEM-STRATEGY.md。

## 2. 现状

### 2.1 E2 前（2026-09-20 立项时的占位状态）

| 位置 | 立项时现状 |
|---|---|
| `tool_dispatchers.py`（原 716 行） | `class MCPDispatcher` 是占位类，`execute()` 直接返回 `MCP bridging not yet available` |
| `tool_dispatchers.py` | `DispatcherRegistry.TOOLTYPE_MAP["mcp"] = [MCP_TOOLS_LIST, MCP_TOOLS_CALL]` |
| `models.py` | `ToolType.MCP_TOOLS_CALL = "mcp.tools.call"` 已定义（`MCP_TOOLS_LIST` 同理） |
| `~/.trimum/tools/mcp/main.py` | 只是把请求转给 `MCPDispatcher()`，无实际协议实现 |
| `tool_gateway.py` | MCP 类型已在 ToolGateway 的类型表内 |
| `config/*.yaml` | 无任何 `mcp_servers` / MCP 相关配置项 |

立项时差距清单：① 无 MCP 协议客户端；② 无 server 生命周期管理；③ 远端工具未聚合进 `ToolRegistry`；
④ 未接入 Policy/SecurityRule/JIT 授权；⑤ 无审计事件；⑥ 无策展白名单。

### 2.2 E2 后（本次实现，M0+M1+M2）

| 差距 | 状态 | 落点 |
|---|---|---|
| ① 协议客户端（stdio） | ✅ | `mcp_client.py`：子进程 + JSON-RPC 2.0 换行分帧，`connect/initialize/list_tools/call_tool/ping/close` |
| ① 协议客户端（HTTP/SSE） | ✅ | `MCPHttpTransport`：POST + JSON/SSE 回包、`Mcp-Session-Id` 复用、404 会话过期、202 无回包、超时/断连分类；`parse_sse_messages()` 独立可测 |
| ② 生命周期 | ✅ | `MCPServerPool`：懒启动、按名复用、坏连接丢弃重建、`close/close_all`；**M4 补齐**空闲回收（`idle_ttl` + 30s 后台回收器）与 `apply_cgroup(pid)` 绑定（读回确认，降级只记录不失败） |
| ③ 工具聚合进 `ToolRegistry` | ⏳ M3 | `ToolRegistry` 目前是静态 `ToolDefinition`（`ToolType` 是枚举），动态工具需要新机制；M2 先由 `mcp.tools.list` 提供运行时枚举 |
| ④ 授权接入 | ✅ 复用 | 调用与内置工具走同一层 ToolGateway 分层；MCP 已在 cwd jail 跳过表内（不碰工作目录） |
| ⑤ 审计 | ✅ | 每次调用记 `mcp_call` 事件（server / tool / 耗时 / 结果 / 参数**键名**），`task.audit.mcp_call` 广播 |
| ⑥ 策展白名单 | ✅ M3 | `config/mcp-catalog.yaml` + `trm mcp catalog import/list`（见 §5.1） |
| ⑦ 常驻池 + 可观测入口 | ✅ M4 | `api_server.start_mcp()` 把共享池交给 `MCP_TOOLS_LIST` / `MCP_TOOLS_CALL` 两个键上的**同一个** dispatcher，起后台回收器；IPC `mcp.status` / `mcp.restart`；`trm mcp status` / `restart` |

### 2.3 M0 决议（2026-09-20 冻结）

1. **自研最小 client，不复用 openai-agents 的 MCP transport**：stdio 分帧就是「一行一个 JSON-RPC 2.0」（LSP 同款），
   `asyncio` 直接够用；把 SDK 引进来等于把 Agent SDK 的取舍绑进协议层。将来若自研 coding Agent 走 openai-agents，
   可在 transport 层替换，`MCPClient` 对外接口（`connect/list_tools/call_tool`）不变。
2. **首批 3 个「非它不可」用例**（M2 验收依据）：
   ① 本机能力接入（`uvx mcp-server-filesystem` 之类本地 server，Agent 不必逐软件写适配器）；
   ② 远程 SaaS 走受管通道（`trust: cloud`，带分层 + 审计 + 确认，避免把 API key 摊在脚本里）；
   ③ 零代码扩能力（用户放一个 `<name>.json5` 即接入，trimum 代码不动一行）。
3. **传输范围**：M2 只做 stdio；HTTP/SSE 留 M4。
4. **调用面约定**：`mcp.tools.list [server]`（空 = 所有已启用）、`mcp.tools.call <server> <tool> [json-arguments]`；
   输出一律 JSON，供 Agent 直接消费。
5. **安全默认**：deny-by-default（`enabled` 缺省 false）；`allow_tools` / `deny_tools` glob（deny 优先）；
   `trust: cloud` 额外继承破坏性工具默认黑名单；参数值不入审计。
6. **测试策略**：`tests/fixtures/mcp_echo_server.py` 是**真协议** stdio server（不是 mock），
   因此分帧、超时、带外通知、进程退出都被真实覆盖；沙箱内不联网、不依赖 Node。

## 3. 生态数据（awesome-mcp-servers 快照）

| 项 | 值 |
|---|---|
| 仓库 | `punkpeye/awesome-mcp-servers` |
| Stars / Forks | 95,293 / 16,367 |
| License | MIT |
| 最近 push | 2026-09-15 |
| 条目总数 | 4,117（`- [name](url) ...` 行） |
| 分类数 | 60+（`### <a name="...">` 小节） |

**语言标记分布**（同一行可多标记）：

| 标记 | 含义 | 条数 |
|---|---|---|
| 📇 | TypeScript / JavaScript | 2,271 |
| 🐍 | Python | 1,351 |
| 🏎️ | Go | 195 |
| 🦀 | Rust | 129 |
| #️⃣ / ☕ / 🌊 / 💎 | C# / Java / C-C++ / Ruby | 31 / 30 / 6 / 2 |

**分发方式关键词命中**：`npx` 626、`pip install` 127、`npm` 110、`uvx` 108、`docker` 85。

**分类 Top 10**：Developer Tools 507、Finance 450、Knowledge & Memory 340、Search & Data Extraction 237、
Security 234、Other Tools 211、Communication 161、Databases 138、Aggregators 134、Cloud Platforms 129；
与 trimum 直接相关的还有 **Browser Automation 104**、**Command Line 26**、**OS Automation 16**、**File Systems 48**、
**Code Execution 22**、**Monitoring 87**。

**关键推论**：TS/npx 派系（2,271 / 626）显著多于 Python（1,351 / 127）。若坚持「去 Node 化」，
策展必须**以 `uvx` / `pip install` / 单二进制（Go/Rust）为优先**，否则 MCP 接入会重新把 Node 引回技术栈。

### 条目解析规则（供策展导入器使用）

格式：`- [owner/repo](url) [![[badge]](badge-url)](glama-url)? <语言emoji> <范围emoji> <OS emoji> - 描述`

图例（README `## Legend`）：语言见上表；范围 ☁️ 云端 / 🏠 本地 / 📟 嵌入式；系统 🍎 macOS / 🪟 Windows / 🐧 Linux。

## 4. 设计草案

### 4.1 模块划分

| 模块 | 职责 |
|---|---|
| `mcp_client.py` | 协议客户端：`stdio`（`create_subprocess_exec` + JSON-RPC 2.0 换行分帧）与 `streamable-http`（POST + SSE）；`initialize` / `tools/list` / `tools/call` / `shutdown` |
| `mcp_registry.py` | 读取 `~/.trimum/mcp/<name>.json5`，维护 server 定义与生命周期（懒启动、空闲回收） |
| `mcp_bridge.py` | 把 `tools/list` 结果映射为 trimum 工具条目，注册到 `ToolRegistry`（命名 `<server>__<tool>`），供 Agent/Planner 感知 |
| `tool_dispatchers.MCPDispatcher` | 由占位改为真实分发：解析 server + tool → 走 client 调用 → 结果脱敏后返回 |

### 4.2 server 定义（文件化）

`~/.trimum/mcp/<name>.json5`：

```json5
{
  name: "filesystem",
  transport: "stdio",              // stdio | http
  command: "uvx",
  args: ["mcp-server-filesystem", "/home/user/work"],
  env: { "MCP_LOG_LEVEL": "warn" },
  trust: "local",                  // local | cloud
  risk: "medium",                  // 决定 ToolGateway 分层策略
  timeout: 30.0,
  enabled: false,                  // deny-by-default：默认不启用
  allow_tools: [],                 // 空 = 全部；非空 = 白名单
  deny_tools: ["*delete*", "*exec*"],
  permissions: { filesystem: [], network: false }
}
```

### 4.3 生命周期与资源

- 一个 server 一个子进程；沿用 `agent_launcher.py` 的既有约定：**输出落日志文件而非 PIPE**
  （避免 64KB 管道写满卡死 + 短命进程的 `Event loop is closed`）。
- 懒启动：首次调用时拉起，空闲 `idle_ttl`（默认 300s，`0` = 常驻）后回收；`trm mcp status/list/restart` 提供可观测入口。
- Linux 上沿用 `apply_cgroup(pid)` 约束资源（与子 Agent 同一套，需 root；非 root 时降级为
  `unavailable (not bound: ...)` 状态，调用照常）。

### 4.4 安全边界（复用现有分层，不新开旁路）

- **deny-by-default**：sever 定义默认 `enabled: false`，需显式开启并写进白名单。
- 调用统一走 `ToolGateway.execute()`：Layer 1 PolicyEngine → Layer 2 Agent 权限 → Layer 2.5 SecurityRule →
  Layer 3 JIT（高风险 server / 高危工具名需一次性授权）。
- **信任分级**：`trust: cloud` 的 server 默认对写类工具强制 confirm；`filesystem`/`shell`/`exec` 类工具名
  一律进 `deny_tools` 默认值。
- **脱敏与审计**：沿用 `_redact_credentials()`；每次调用记 `mcp.call` 审计事件（server / tool / 耗时 / 结果状态），
  入 `audit.jsonl` 并经 EventBus 广播 `task.audit.mcp_call`。
- **输出限长**：MCP 返回经 `ContextCompactor` 限长，防止大 payload 冲垮上下文。

## 5. 引入 awesome-mcp-servers 的三种姿势

| 姿势 | 做法 | 评价 |
|---|---|---|
| **A. 人工策展** | 只把 awesome 列表当参考，手工挑 5-10 个 server 写进 `~/.trimum/mcp/` | 起步推荐；可控、可测 |
| **B. 策展导入器**（推荐中期） | 脚本拉 README → 按「条目解析规则」切分 → 过滤语言/分发方式/分类 → 生成候选清单 `config/mcp-catalog.yaml` → 人工审核后才进 `~/.trimum/mcp/` | 与 awesome 列表解耦，可复跑；候选库不自动启用 |
| **C. 全量导入** | 4,117 条全进目录 | 不建议：绝大多数与本机场景无关，且审计成本极高 |

建议的候选库条目：

```yaml
# config/mcp-catalog.yaml（导入器产物，人工审核后转为 enabled: true）
- repo: modelcontextprotocol/servers
  name: filesystem
  category: file-systems
  lang: python
  dist: uvx
  trust: local
  reviewed: false        # true 才允许写入 ~/.trimum/mcp/
  notes: "官方参考实现，读写白名单目录"
```

### 5.1 导入器用法（M3 已实现，2026-09-20）

```bash
# 预览：不写文件，只报「选了多少 / 每条红线拦了多少」
trm mcp catalog import --dry-run

# 生成候选清单（写入 config/mcp-catalog.yaml；文件已存在时需 --force）
trm mcp catalog import

# 审核入口：按分类 / 分发 / 语言筛，或只看还没审的
trm mcp catalog list --category file-systems --dist uvx
trm mcp catalog list --unreviewed
```

实测（2026-09-20 快照，`tmp/research/awesome-README.md`）：

| 分档 | 条数 |
|---|---|
| 上游 README 条目 | 4,118 |
| **通过红线 → 候选** | **232**（uvx 104 / pip 110 / cargo 10 / docker 5 / go 2 / uv 1；本地 170、云端 62） |
| 拦下 · 语言不合格 | 2,480（ts 2,219 / unknown 197 / java 29 / csharp 28 / c_cpp 5 / ruby 2） |
| 拦下 · 描述里没有安装方式（`dist:unknown`） | 1,356 |
| 拦下 · Node 派系（npx 14 / npm 2） | 16 |
| 拦下 · 其他分发（brew） | 7 |
| 拦下 · 不在 `Server Implementations` 小节 | 27 |

**审核流程（人工，三步）：**

1. `trm mcp catalog list --unreviewed --category <id>` 挑条目，读 `description` / `flags` / `install_hint`；
2. 把要启用的条目 `reviewed` 改成 `true`（可加 `note`）—— 改这一个字段**不会启用任何东西**；
3. 手工写成 `~/.trimum/mcp/<name>.json5` 并显式 `enabled: true`，走 §4.2 的 deny-by-default 注册。

`flags` 是给审核人看的提示：`no-install-hint`（没写安装方式）/ `unknown-scope`（缺范围标记）/
`scope-mixed`（本地+云端都标）/ `multi-language` / `embedded` / `no-linux`。

重新导入（`--force`）按 `repo` 保留已有条目的 `reviewed` / `name` / `note`，审核工作不会被下一次刷新冲掉；
`--include-npx` / `--all-languages` / `--include-unknown-dist` 可以把被红线拦掉的条目放回来（默认不收，
但它们始终以计数形式出现在产物摘要里，不会被静默丢弃）。
## 6. 阶段计划

| 阶段 | 内容 | 验收 |
|---|---|---|
| **M0** ✅ | 冻结本方案；确认真实需求场景（3 个「非它不可」用例）（2026-09-20 完成） | 决议见 §2.3 |
| **M1** ✅ | `mcp_client.py` stdio 客户端 + `initialize` / `tools/list` / `tools/call`（2026-09-20 完成） | `tests/test_mcp_client.py`（16 项，真实 fixture server + 超时/EOF/带外通知） |
| **M2** ✅ | `mcp_registry.py` + `MCPDispatcher` 实装 + ToolGateway 审计回填 + `mcp_call` 事件（2026-09-20 完成） | `tests/test_mcp_registry.py`（27）/ `test_mcp_dispatcher.py`（30）；`trm mcp list/tools/call/paths` 可用 |
| **M3** ✅ | 策展导入器（姿势 B）+ `config/mcp-catalog.yaml` + 审核流程文档（2026-09-20 完成，用法见 §5.1） | `tests/test_mcp_catalog.py`（52 项：离线 fixture + 真实快照）→ 232 条候选，红线逐条可解释 |
| **M4** ✅ | HTTP/SSE 传输 + 空闲回收 + cgroup 绑定 + 常驻池接线 + `trm mcp status/restart` + 运维文档（2026-09-20 完成，见 §6.1） | 新增 **71** 项测试（`test_mcp_http_transport.py` 29 / `test_mcp_lifecycle.py` 18 / `test_mcp_daemon.py` 24）；真机 Ubuntu 隔离 daemon 验收 **16 PASS / 0 FAIL**；全量 825 passed / 8 failed（本地，8 项为既有 Windows 沙箱基线）/ 827 passed / 11 failed（真机，11 项为既有宿主状态基线） |

### 6.1 M4 落地（2026-09-20）

| 子项 | 落点 |
|---|---|
| HTTP / SSE 传输 | `mcp_client.MCPHttpTransport`（`httpx` 可选导入）+ `parse_sse_messages()`；`MCPClient.start()` 按传输名分派，`initialize` 回写协商到的协议版本 |
| 空闲回收 | `MCPServerPool.reap(now)` / `start_reaper(interval)` / `stop_reaper()`；`idle_ttl: 0` = 常驻；`clock` 可注入（测试不睡真实时间） |
| cgroup 绑定 | `MCPServerPool._bind_cgroup()` + `_verify_cgroup()`（读回 `assigned_pids` 再报状态，不把「调用没报错」当成成功）；`ResourceController.assigned_pids()` 为非抽象默认实现 |
| daemon 接线 | `api_server.build_mcp_pool()` / `wire_mcp_dispatchers()` / `start_mcp()`；`AppState.mcp_pool` + `mcp_reaper`；shutdown 时 `close_all()` |
| 可观测 | IPC `mcp.status` / `mcp.restart`；CLI `trm mcp status`（有 daemon 走 IPC、否则本地读定义）/ `trm mcp restart <server>`（无 daemon 时「起一次证明可用再关掉」） |
| 运维文档 | `docs/OPERATIONS.md` 新增「MCP server 运维（M4）」；`scripts/sync_opt_m4.sh`（sudo 安装，sha256 校验）；`scripts/accept_m4.py`（隔离 daemon 验收） |

真机验收（Ubuntu，2026-09-20，`scripts/accept_m4.py`，**16 PASS / 0 FAIL**）：8323 端口隔离 daemon 接线后
`mcp.status` 的 `source=daemon`；`mcp.restart` 停旧起新（pid 14091 → 14095）；`idle_ttl=5` 的 server 被后台
回收器回收、`idle_ttl=300` 的不受影响；`streamable-http` 定义在真机上完成真实往返（列出 7 个工具）；
不存在的 server 报 `not found` 而非静默成功。该轮同时暴露并修掉两个真缺陷：

1. `trm --config X mcp status` 用的是默认 config（`Config()` 写死），会去问**另一个** socket 上的 daemon，
   失败后静默退回本地一次性路径 —— 改为走 `load_config(args)`（`tests/test_mcp_daemon.py` 有回归用例）。
2. daemon 长驻后 `MCPRegistry` 缓存不再失效，热插定义要等重启才可见（违背「放个文件就接入」的承诺）——
   `MCPRegistry._ensure_fresh()` 按目录指纹（名字 / mtime / 大小）重读（`TestDropInDefinitions` 覆盖）。
3. 定义被删掉 / 写坏后，已在跑的 client 要等 `DEFAULT_IDLE_TTL`（300s）才被收回，而此刻 dispatcher 已经查不到它，
   进程纯属残留：`reap()` 改为对「定义已消失」直接回收（`test_a_deleted_definition_closes_the_running_client`）。

## 7. 风险与未决问题

1. **Node 回流风险**：npx 派系占多数，需明确「只收 Python/uvx/单二进制」的筛选红线。
2. **信任模型**：`trust: cloud` server 会把本机数据送出，需要用户在 enable 时显式确认（配 confirm 通道）。
3. **协议版本漂移**：MCP 规范仍在演进，需在 `mcp_client` 里做版本协商与降级。
4. **与 openai-agents-python 的关系**：该库自带 MCP 支持，若 Agent SDK 走它，可复用其 transport 层而
   不重复造轮子 —— **M0 需先做这个取舍**（自研 vs 复用 SDK）。
5. **待用户确认**：首批要接入的具体 server 清单（决定 M1 的冒烟目标）。

## 8. 原始件

| 文件 | 内容 |
|---|---|
| `tmp/research/awesome-README.md` | 列表 README（1.7 MB，4,117 条目，可作导入器 fixture） |
| `tmp/research/awesome-repo.json` | 仓库元数据 |
