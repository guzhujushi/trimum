# trimum — 待办清单

> 最后更新：2026-09-19 15:45
> 当前阶段：Phase 3.5 收尾 — trimum CLI 规划
> 测试：355 passed（2026-09-19）；远程 33/33 import 全过
> 当前分支：`ubuntu`（最新）

---

## 核心理念

**trimum 不是一次性代码冲刺，是长期成长的项目。** 以下清单按"下一步最有价值"排序。

---

## 🎯 当前主线：trimum CLI（`trm` 命令）

> 目标：根据 README.md 的 CLI 规划，构建完整、统一的 `trm` 命令行接口。
> 参考：README 中已列出 CLI 全部子命令，`main.py` 已有 `cli_dispatch()` 骨架。

### 📋 CLI 完整命令规划

```
trm                                # 查看帮助（默认显示可用子命令）
trm version                        # 显示 trimum 版本
trm health                         # 快速健康检查（不需要 daemon）
trm status                         # 查看当前 Agent 运行状态 / 资源占用
trm doctor                         # 检查环境依赖 / 配置完整性

trm ask "<自然语言指令>"            # 单次提问（LLM 规划并执行）
trm ask -i 或 --interactive        # 交互式多轮对话（流式输出）
trm ask ... --agent shell          # 指定 agent
trm ask ... --agent plan           # 指定 planner agent

trm memory list                    # 列出所有记忆分类（domain + category）
trm memory get <key>               # 取某条记忆
trm memory set <key> <value>       # 写入一条记忆（自动分类）
trm memory search "<关键词>"       # 按内容搜索记忆
trm memory stats                   # 查看记忆数量统计

trm security status                # 查看安全策略状态
trm security allow-once <agent_id> [--tool shell] [--cmd "ls -la"] [--ttl 300]
                                   # 签发一次性临时授权 token
trm security tokens                # 列出当前有效 token

trm daemon start                   # 以守护进程模式运行（默认）
trm daemon stop                    # 停止 daemon
trm daemon restart                 # 重启 daemon
trm daemon status                  # 查看 daemon 状态

trm log tail                       # 实时 tail 运行日志
trm log --audit                    # 只显示结构化审计日志（JSON 行）
trm log --since 1h                 # 按时间过滤日志

trm tool list                      # 列出已注册的所有工具
trm tool info <tool_name>          # 查看工具详情

trm agent list                     # 列出所有 agent
trm agent info <agent_id>          # 查看 agent 详情
trm agent spawn <agent_id>         # 启动新 agent

trm workflow list                  # 列出所有 workflow
trm workflow run <workflow_name>   # 运行 workflow
trm workflow status <run_id>       # 查看 workflow 运行状态

trm config show                    # 显示当前配置
trm config set <key> <value>       # 设置配置项
```

### 🗂️ 实施步骤（建议顺序）

#### Phase A：CLI 框架重构（P0）
- [ ] **A1. 引入 argparse 子命令结构** refactor `cli_dispatch()`
  - 从 `sys.argv` 手动判断改为规范的 `argparse` 子解析器
  - 建立 `trm` 顶层命令 → 子命令 → 子子命令的三层结构
  - 实现 `--help` 输出 README 中所列命令的完整帮助信息
- [ ] **A2. 创建 `src/trimum_core/cli/` 模块包**
  - 按功能拆分为独立模块：`cli/commands/*.py`
  - 减少 `main.py` 的臃肿，`main.py` 仅保留入口转发
- [ ] **A3. 统一输出格式化**
  - 普通输出 / `--json` 模式（机器可读）
  - 颜色高亮（有 TTY 时）
  - 支持 `--quiet` 静默模式

#### Phase B：核心命令完善（P1）
- [ ] **B1. `trm status` / `trm health` 增强**
  - 显示 daemon 运行状态 PID、端口、uptime
  - 显示资源占用（内存/CPU，可复用 ResourceController 数据）
  - 检查各核心模块加载状态（每项 ✓/✗）
- [ ] **B2. `trm doctor` 环境检查**
  - Python 版本要求检查（>= 3.12）
  - 依赖包完整性检查（requests, httpx, rich 等）
  - `~/.trimum/` 目录结构检查（agents/ tools/ memory/ logs/ config.yaml）
  - API Key 配置检查（DEEPSEEK_API_KEY 等，只报告存在与否，不泄露）
  - 网络连接测试（到 API 端点的连通性）
- [ ] **B3. `trm memory` 命令组**
  - 对接现有 `MemoryClassifier` + SQLite 存储
  - `list`：按 domain/category 分类展示
  - `get <key>`：取单条
  - `set <key> <value>`：写入并自动分类
  - `search <query>`：调用 `memory_search` 语义检索
  - `stats`：显示各分类记忆数量统计
- [ ] **B4. `trm security` 命令组扩展**
  - 现有 `allow-once` 保留
  - 新增 `status`（策略状态）
  - 新增 `tokens`（列出有效 token）
  - 新增 `revoke <token_id>`（撤销 token）

#### Phase C：Agent 交互命令（P2）
- [ ] **C1. `trm ask` 体验优化**
  - 单次提问模式：`trm ask "..."` → 流式输出 → 显示 token 统计
  - `--interactive` 模式：使用 `rich` / `prompt_toolkit` 实现 REPL
  - Ctrl+C 中断处理
  - 会话记忆挂载（复用已有三重记忆架构）
- [ ] **C2. `trm agent` 命令组**
  - `list`：列出所有注册 agent（从 Agent Registry 读取）
  - `info <id>`：显示 agent 详情（权限、工具集、状态）
  - `spawn <id>`：启动新 agent 实例
  - `kill <id>`：停止 agent 实例

#### Phase D：Workflow & 工具命令（P3）
- [ ] **D1. `trm workflow` 命令组**
  - `list`：列出所有 workflow 定义
  - `run <name>`：执行 workflow
  - `status <run_id>`：查看运行状态/结果
  - `log <run_id>`：查看运行日志
- [ ] **D2. `trm tool` 命令组**
  - `list`：列出所有已注册工具（Tool Registry）
  - `info <name>`：查看工具详情（参数、权限等级）

#### Phase E：配置与日志（P4）
- [ ] **E1. `trm config` 命令组**
  - `show`：显示当前生效配置
  - `set <key> <value>`：设置配置项
  - `get <key>`：查询单项配置
- [ ] **E2. `trm log` 命令组**
  - `tail`：实时 tail 日志（支持 `-f`）
  - `--audit`：审计日志过滤
  - `--since <duration>`：时间过滤
- [ ] **E3. `trm` 默认行为**
  - 无参数时打印帮助 + 当前 daemon 状态
  - 美化 banner/help 输出

#### Phase F：测试与发布（P4）
- [ ] **F1. CLI 单元测试**
  - `tests/test_cli.py`：每个子命令的参数解析、返回值
  - Mock daemon/RPC 层，不依赖真实服务
- [ ] **F2. 集成测试**
  - 真实起 daemon 后 `trm status` / `trm health` 连通性
  - `trm ask` 端到端流程
- [ ] **F3. 打包验证**
  - 确认 `pyproject.toml` 中 `trm` 入口正确
  - 编写 README 完整 CLI 使用文档

---

## 🟡 后续方向（CLI 完成后）

### CLI 进阶
- [ ] `trm ask` 墨迹/屏幕截图输入支持
- [ ] `trm memory import` / `export`（记忆迁移）
- [ ] CLI 别名自定义（`.trimumrc` 配置文件）
- [ ] 自动补全脚本（bash/zsh/fish）

### 其他待办（承接之前）
- [ ] **#3.8 Browser Tool 后端收尾**：标记 opencli 为 deprecated（已完成修复，待验证）
- [ ] **Safety**: Landlock / Seccomp 沙箱（Phase 4）
- [ ] **3.5 确定性字段 confidence 分级**：三级分流（直接执行 / 确认窗口 / 转 Planner）
- [ ] **API Key Manager**：统一管理所有需要 API Key 的点

---

## ✅ 已完成（2026-09-19 确认）

| 任务 | 状态 |
|---|---|
| **#3.8 Browser Tool (CLI-Anything) 集成** | ✅ General → Browser 路由问题已修复，355 tests pass |
| **CLI-Anything 排查（Chrome/CDP/Python）** | ✅ 所有 4 个问题已解决 |

---

## 🧪 测试状态

| 项目 | 状态 |
|------|------|
| 本地全量测试 | 355 passed (2026-09-19) |

---

## 克隆/分支同步

| 分支 | 状态 | 备注 |
|------|------|------|
| `ubuntu` | ⭐ 最新 | 当前开发分支，已 push |
| `main` | ⏳ 需同步 | Phase 3 + CLI 后跟进 |
| `server` | ⏳ 需同步 | 同上 |
| `arch-linux` | ⏳ 需同步 | 同上；ipc_handler.py 需手动 cherry-pick |
