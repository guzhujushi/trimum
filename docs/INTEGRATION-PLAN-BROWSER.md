# 浏览器工具集成方案：CLI-Anything + Obscura 替代 OpenCLI

> 状态：规划中
> 日期：2026-09-18

## 背景

OpenCLI (TypeScript) 的 ToolBridge 运行不了（Node 依赖问题）。
用户要求用 Obscura 和 CLI-Anything 替代。

## 关键发现

1. **CLI-Anything** (python) 已经内置了完整的浏览器工具生态：
   - `browser` — DOMShell MCP server，Chrome 浏览器自动化
   - `browser-cdp` — 通过原始 Chrome DevTools Protocol
   - `clibrowser` — 零依赖 CLI 浏览器（轻量搜索）
   
2. **Obscura** (Rust) 是一个无头浏览器引擎库：
   - 独立二进制，不需要 Chromium
   - 兼容 CDP 协议
   - 内存仅 30MB vs Chromium 200MB+
   - 当前 Windows 没有 Rust/cargo 环境

## 推荐方案

### 方案 A：CLI-Anything browser 为主，Obscura 备用（推荐）

```
Claude/AI Agent
    │
    ▼
trimum 工具层 (Python)
    │
    ├── browser (CLI-Anything) → 完整浏览器自动化
    │     └── 需要 Chrome 或 Edge 浏览器
    │
    ├── browser-cdp (CLI-Anything) → 裸 CDP 控制
    │     └── 需要 Chrome 或 Edge 浏览器
    │
    └── clibrowser → 轻量搜索（不需要浏览器）
          └── 零依赖，适合快速获取网页内容

Obscura（备用/未来）：
    ├── 当 Windows 装了 Rust 之后可编译
    ├── 服务器端生产环境推荐
    └── 三种形态可用
```

### 方案 B：Obscura 为主（未来/服务器端）

```
AI Agent → trimum → Obscura (Rust 二进制) → 页面渲染
```

- 优点：不需要安装 Chrome，反检测，轻量
- 缺点：需要 Rust 环境，当前无法直接使用

## 集成步骤

### Step 1：安装 CLI-Anything 浏览器工具

```bash
# 安装 CLI-Anything hub
pip install cli-anything-hub

# 安装浏览器工具
cli-hub install browser
cli-hub install browser-cmd

# 查看已安装
cli-hub list
```

### Step 2：trimum 工具层集成

在 `tool_gateway.py` 中添加新的工具注册：

```python
ToolDefinition(
    name="browser",
    description="通过 DOMShell 控制浏览器，支持打开页面、点击、填表、截图",
    tool_type=ToolType.BROWSER,
    executable="browser",
    allowed_flags=["open", "click", "type", "screenshot", "evaluate"],
    timeout_default=30.0,
    risk_level=RiskLevel.MEDIUM,
)
```

### Step 3：OpenCLI 桥接弃用

- 在 `tool_gateway.py` 中标记 `opencli` 为已废弃
- 移除或注释掉 OpenCLI 适配器的加载逻辑
- 保留 `tool_file_loader` 的扩展机制（其他 CLI 工具继续使用）

## 验证清单

- [ ] `browser` 工具能打开网页
- [ ] `browser` 工具能截图
- [ ] `browser` 工具能执行 JS
- [ ] `browser-cdp` 能绕过反机器人检测
- [ ] 登录状态能保存（cookie persistence）
- [ ] token 消耗数据能记录

## TODOs

1. [ ] 等待 CLI-Anything browser 安装完成
2. [ ] 在 trimum tool_gateway 中注册 browser 工具
3. [ ] 写一个 demo：让 Agent 浏览网页并返回内容摘要
4. [ ] 验证 cookie 持久化（登录状态复用）
5. [ ] 测试反检测能力
6. [ ] 同步到 Ubuntu（仅当 Ubuntu 有 Chrome 时）
7. [ ] 评估 Obscura 编译到 Windows 的可行性
