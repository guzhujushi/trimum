# MCP 接入方案 — awesome-mcp-servers 引入准备

> 日期：2026-09-20
> 数据来源：`punkpeye/awesome-mcp-servers`（经 7993 代理抓取，原始件在 `tmp/research/awesome-README.md`）
> 结论先行：trimum 目前**没有任何真实 MCP 能力**（`MCPDispatcher` 是占位）。引入 awesome-mcp-servers 的第一步
> 不是「抄列表」，而是实现 MCP 客户端 + 文件化 server 注册 + 权限接入。

## 1. 目标与范围

- 目标：让 trimum 能像用内置工具一样调用 MCP server 暴露的工具，且**全部调用受 Tool Gateway 管辖**。
- 范围：MCP 客户端（stdio / HTTP）、server 定义文件化、工具聚合、鉴权与审计、策展目录。
- 非目标：不把 awesome-mcp-servers 的 4,117 个条目全量引入；不做 MCP server 的托管与市场分发。
- 生态定位：MCP 是四层生态战略中的「服务层」，见 docs/ECOSYSTEM-STRATEGY.md。

## 2. 现状（代码核实，2026-09-20）

| 位置 | 现状 |
|---|---|
| `src/trimum_core/tool_dispatchers.py:716` | `class MCPDispatcher` 是占位类，`execute()` 直接返回 `MCP bridging not yet available` |
| `src/trimum_core/tool_dispatchers.py:763` | `DispatcherRegistry.TOOLTYPE_MAP["mcp"] = [MCP_TOOLS_LIST, MCP_TOOLS_CALL]` |
| `src/trimum_core/models.py:408` | `ToolType.MCP_TOOLS_CALL = "mcp.tools.call"` 已定义（`MCP_TOOLS_LIST` 同理） |
| `~/.trimum/tools/mcp/main.py` | 只是把请求转给 `MCPDispatcher()`，无实际协议实现 |
| `src/trimum_core/tool_gateway.py:1014` | MCP 类型已在 ToolGateway 的类型表内 |
| `config/*.yaml` | 无任何 `mcp_servers` / MCP 相关配置项 |

**差距清单**：① 无 MCP 协议客户端（stdio + streamable HTTP/SSE）；② 无 server 生命周期管理；
③ 远端工具未聚合进 `ToolRegistry`，Agent 无从感知；④ 未接入 Policy/SecurityRule/JIT 授权；
⑤ 无审计事件；⑥ 无策展白名单。

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
- 懒启动：首次调用时拉起，空闲 `idle_ttl`（默认 300s）后回收；`trm mcp status/list/restart` 提供可观测入口。
- Linux 上沿用 `apply_cgroup(pid)` 约束资源（与子 Agent 同一套，需 root / `trmd.service`）。

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

## 6. 阶段计划

| 阶段 | 内容 | 验收 |
|---|---|---|
| **M0** | 冻结本方案；确认真实需求场景（先列 3 个「非它不可」的用例） | 本文档评审通过 |
| **M1** | `mcp_client.py` stdio 客户端 + `initialize` / `tools/list` / `tools/call` | 单测（mock server）+ 真实 server 冒烟各 1 例 |
| **M2** | `mcp_registry.py` + `MCPDispatcher` 实装 + ToolGateway 分层接入 + 审计事件 | `tests/test_mcp_client.py` / `test_mcp_registry.py`；`trm mcp list` 可用 |
| **M3** | 策展导入器（姿势 B）+ `config/mcp-catalog.yaml` + 用户文档 | 导入器单测（离线 fixture：`tmp/research/awesome-README.md`） |
| **M4** | HTTP/SSE 传输 + 空闲回收 + cgroup 绑定 + 运维文档 | 长跑测试 + `docs/OPERATIONS.md` 补 MCP 章节 |

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
