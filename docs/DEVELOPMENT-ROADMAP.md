# trimum 开发路线图

> 最后更新：2026-09-02

---

## Phase 0：基础环境 ✅ 已完成
- Arch Linux + Python + Docker + Git

## Phase 1：AI Shell MVP ✅ 已完成
- 自然语言 → 安全执行 → 输出
- `trm` 命令行工具

## Phase 1.5：桌面预设 ✅ 已完成
- 22 套 Hyprland 主题预设（继承自 Omarchy 社区）
- Btrfs + Snapper 自动配置
- 一键安装脚本

## Phase 2：Harness Core ✅ 已完成（2026-08-31）
> 17 个模块，~4300 行代码，33 项测试全部通过

### 包含组件
- **Harness Runtime** — Agent 生命周期、权限、资源管理
- **Agent Router** — 按能力匹配 Agent，管道构建
- **Event Bus** — 异步 pub/sub 系统事件
- **Workflow Engine** — DAG 任务编排（并行/串行/依赖链）
- **Tool Gateway** — Tool Registry + Agent 权限感知（双层检查）
- **Security Runtime** — Policy Engine（YAML 规则 + Risk Level）
- **Planner Agent** — 唯一 LLM 组件，按需启动

## Phase 3：Agent SDK + 安全体系（进行中）

### 核心工作
- Agent SDK 封装（集成 openai-agents-python）
- 上下文窗口管理（Compaction / Tool Output Limits）
- 可观测性基座（Token 计数 / 结构化日志 / 成本追踪）
- 凭据脱敏（Secrets Redaction）
- cwd Jail 工作目录隔离
- AI/人类流量区分标签
- JIT 一次性授权模式
- 子 Agent 资源配额
- 结构化审计日志
- 流式 CLI 输出

详情见 `TODO.md` #3 ~ #3.9。

## Phase 4：Security Runtime（待开始）

### 目标
用 Linux 内核机制加固 Agent 执行环境。

### 实现路径
```
Level 0：直接执行（低风险）
Level 1：Landlock + Seccomp（中风险）
Level 2：Namespace（User/Mount）轻量隔离
Level 3：Docker 沙箱（高风险完整隔离）
```

### 依赖
- Linux 5.13+（Landlock）
- Docker（沙箱模式）

## Phase 5：Memory Layer + 开发者工具链（待开始）

### 目标
落地长期记忆 + Knowledge Store + 声明式工具链预装。

### 记忆与知识
| 子层 | 技术选型 |
|---|---|
| 长期记忆 | SQLite（轻量） |
| 向量检索 | chroma（pip 秒装）或 SQLite + numpy |
| 关键字搜索 | SQLite FTS5 |
| Embedding | BGE-small 或 E5 |

### 声明式开发者工具链
工具链不写死在 install.sh，而是通过 `config/trimum.yaml` 声明：

```yaml
tools:
  categories:
    editor: [nvim, code]
    vcs: [git, lazygit, gh]
    lang: [python, nodejs, rust]
    debug: [btop, ripgrep, fd, jq, fzf]
    container: [docker, docker-compose]
    db: [sqlite3, psql]
```

- `trm tools detect` — 扫描 PATH，检测实际安装了哪些工具
- `trm tools list` — 展示已安装的工具链
- `trm tools missing` — 对比 config 和实际，列出缺失项
- Tool Registry 自动注册已检测到的工具

### 主题规范标准化
- 补全 `docs/THEME-SPEC.md` — 标准化 colors.toml 字段定义
- 主题切换器从 Shell 脚本升级为 `trm theme list / set / preview` CLI 子命令
- 主题文件统一放在 `~/.trimum/themes/`（Agent 文件化思路一脉相承）

---

## Phase 6：ISO / 安装镜像（待开始）

### 目标
一键安装镜像，任何 x86_64 机器上从零到完整 AI Linux 桌面。

### 三档安装模式
| 模式 | 内容 | 磁盘 |
|---|---|---|
| 🌟 普通模式 | AI Desktop + 浏览器 | ~10-20GB |
| 🚀 开发者模式 | 普通 + IDE/AI编码/Docker | ~40-60GB |
| 🧪 AI Engineer | 开发者 + 本地模型/GPU/RAG | 100GB+ |

### 包管理分发
- 本机：通过 AUR / Arch Linux 包（PKGBUILD + `pacman -S trimum`）
- Debian 系：APT 仓库，deb 打包
- 服务器端：`apt.guzhujushi.cn` / `pacman.guzhujushi.cn`（阿里云）

---

## Phase 7：前端控制台 + 生态市场（待开始）

> trimum 从一个守护进程，升级为**有完整 UI 的 AI 操作系统控制台**。

### 7.1 前端控制台

技术栈未定（Electron / Tauri / Web），核心功能模块：

#### 桌面管理
- 22 套主题实时预览 + 一键切换
- 壁纸浏览 / 自定义上传
- 桌面组件（Waybar 等）配置可视化

#### Agent 管理
- Agent 目录（已激活 / 可激活 / 不可用）
- 每个 Agent 详情：能力描述、依赖工具、Workflow 示例
- Agent 运行状态（运行中 / 空闲 / 异常）

#### Tool / Workflow 管理
- Tool Registry 可视化——已安装工具列表 + 版本
- Workflow 编辑 / 预览——DAG 图展示
- Workflow 运行历史（成功 / 失败 / 运行中状态追溯）

#### 监控面板
- 系统资源（CPU / 内存 / 磁盘 / 网络）——从 psutil 拉取
- Agent 运行时状态——哪个在跑、跑了多久、用了多少 token
- Workflow 执行过程实时监控——步骤级进度
- Event Bus 实时流——类似系统日志的滚动视图

#### 安全与审计
- 策略规则编辑（Policy Engine YAML 的前端界面）
- 审计日志浏览 + 搜索 + 导出
- 弹窗确认中心（`SecurityAgent.confirm()` 的 UI 归宿）

### 7.2 CLI 工具的集成原则

**统一"发现 + 配置 + 启动入口"，不统一"操作界面"。**

| 做 | 不做 |
|---|---|
| 前端展示已安装的工具列表 | 重写 lazygit 的 Git 界面 |
| 前端编辑 lazygit 的 keybinding 配置 | 把 neovim 改成 Web 编辑器 |
| 一键从面板启动某个 TUI 工具 | 给 ripgrep 做个 Web 版搜索界面 |
| btop 数据在面板上展示（psutil 拉，非重绘） | 重制终端模拟器 |

边界明确：**如果工具的 TUI 本身已经很好用，trimum 只做它的启动器 + 配置管理中心。只有当能力在终端里根本没有 UI（如 Workflow 编辑）时，才在前端完整实现。**

### 7.3 Agent 生态：有条件激活

不内置所有 Agent，而是**探测用户的实际环境，按需激活**。

```json5
// ~/.trimum/agents/tool-detected/git/agent.json5
{
  name: "git-agent",
  display_name: "Git Agent",
  depends_on: ["git", "gh"],
  auto_activate: true,            // 检测到依赖时自动激活
  description: "Git 版本控制助手 —— PR 审查、冲突解决、提交信息生成"
}
```

`trm tools detect` 扫描 PATH → 发现 git → 标记 git-agent 为 active。

可激活的 Agent 示例：

| 检测工具 | 激活的 Agent | 能力 |
|---|---|---|
| `git` / `gh` | git-agent | PR 审查 / 冲突解决 / 提交信息生成 / Changelog |
| `docker` / `docker-compose` | docker-agent | 编排 / 日志分析 / 镜像管理 |
| `codex` CLI | codex-agent | 委派复杂编码任务 |
| `npm` / `pnpm` / `yarn` | node-agent | 依赖分析 / 版本更新 / 构建优化 |
| `kubectl` | k8s-agent | 集群管理 / 部署回滚 |
| `rustc` / `cargo` | rust-agent | 构建 / 依赖管理 |
| `pytest` | test-agent | 测试运行 / 失败分析 / 覆盖率 |
| `ffmpeg` | media-agent | 媒体处理 |
| `psql` / `sqlite3` / `mysql` | db-agent | 数据库查询 |
| `ansible` / `pyinfra` | deploy-agent | 自动化部署 |

未检测到 → 不出现在 Agent Registry，前端不显示。

### 7.4 生态市场

利用阿里云服务器（`8.145.36.108`）搭建 trimum 生态中心。

#### 分发方式

| 渠道 | 内容 | 安装方式 |
|---|---|---|
| 主题市场 | 来自 Omarchy 社区和第三方 | `trm theme install <name>` |
| Agent 市场 | 社区贡献的 Agent | `trm agent install <name>` |
| Tool 市场 | 第三方 Tool Dispatcher | `trm tool install <name>` |
| Workflow 市场 | 预置和社区 Workflow 模板 | `trm workflow install <name>` |
| 包管理器 | trimum 本体 | `pacman -S trimum` / `apt install trimum` |

#### 主题市场

- 连接 Omarchy 社区的主题仓库（22+ 现有主题）
- 用户可通过前端浏览、预览、一键安装
- 支持自定义主题上传到社区

#### Agent / Tool / Workflow 市场

用户通过 trimum 前端或 CLI 发布和下载：

```bash
# 发布
trm agent publish ./my-awesome-agent    # 打包上传到服务器
trm tool publish ./custom-dispatcher

# 下载
trm agent search "code review"
trm agent install code-review-agent

trm workflow search "daily backup"
trm workflow install daily-backup
```

服务器的包索引结构（JSON）：
```json
{
  "agents": [
    {
      "name": "code-review-agent",
      "version": "1.0.0",
      "depends_on": ["git"],
      "description": "自动代码审查 + 风格检查",
      "download_url": "https://market.guzhujushi.cn/agents/code-review-agent.tar.gz"
    }
  ],
  "tools": [...],
  "workflows": [...],
  "themes": [...]
}
```

#### 用户发布

前端提供表单：
- 填写名称 / 描述 / 版本 / 依赖工具
- 上传文件（Agent = agent.json5 + main.py；Workflow = YAML）
- 提交后进入审核或直接发布

#### 包管理器分发

- APT 仓库：`apt.guzhujushi.cn`，deb 打包（Debian / Ubuntu / Mint）
- Pacman 仓库：`pacman.guzhujushi.cn`，PKGBUILD（Arch / Manjaro / EndeavourOS）
- 安装：`sudo apt install trimum` 或 `yay -S trimum`

---

## 时间线预期

| Phase | 状态 | 预计完成 |
|---|---|---|
| Phase 0 | ✅ | — |
| Phase 1 | ✅ | — |
| Phase 1.5 | ✅ | — |
| **Phase 2** | **✅ 已完成** | **2026-08-31** |
| Phase 3 | 🚧 进行中 | 待定 |
| Phase 4 | 📝 设计完成 | Phase 3 后 |
| Phase 5 | 📝 设计完成 | Phase 4 后 |
| Phase 6 | 📝 大纲 | Phase 5 后 |
| Phase 7 | 📝 大纲 | Phase 6 后 |

每个阶段独立可交付，不依赖后续阶段。Phase 7 的前端工作可以与 Phase 5/6 并行开展框架搭建。
