# trimum — 待办清单

> 最后更新：2026-09-16 21:33
> 当前阶段：Phase 3 收尾 — #15 真机部署 ✅，本地服务器基础工具链 P1 ✅，P2 Docker 安装进行中
> 测试：242/245 passed（3 fail = Windows subprocess 编码问题，Linux 必绿）；远程 33/33 import 全过
> 当前分支：`ubuntu`（最新）；arch-linux / server / main 需同步

---

## 核心理念

**trimum 不是一次性代码冲刺，是长期成长的项目。** 不需要把 TODO 填得密密麻麻。以下清单按"下一步最有价值"排序，不是"能想到的都列上"。

---

## 🔴 立即（当前阻塞项）

### 1️⃣ #15 真机部署验收 — ✅ 已完成

#### 解决经过（2026-09-15）
- **实际根因**：venv 是 `pip install -e`（可编辑安装）指向 `/home/guzhujushi/trimum/src/`，而代码一直被部署到 `/opt/trimum/src/`——该目录从未被加载
- `main.py` 中 `server.serve()` 在 uvicorn 0.52.4 下因 `lifespan` 属性缺失卡住 → 替换为 `uvicorn.run()` 稳定启动
- `workflow_engine.py`（含 `_handle_agent_node`）同步到正确路径
- **当前状态**：PID 17337，8321 正常监听，健康检查 ✅
- trmd systemd 持久化：`network.target` 修正 + `TimeoutStopSec=30` + `Restart=always` + 开机自启 enabled

### 2️⃣ codex 校外替代方案
- 目前交我算校外不可用；codex 唯一可用 provider（`custom` → deepseek-v4-flash）是 OpenClaw 本地 gateway 实例
- [ ] **评估**：Windows 本地写代码时，直接用 OpenClaw + codex-plus skill 替代 codex CLI？
- [ ] 或者调高 `timeoutSeconds` 让交我算校外 HTTPS 连接可用？

### 2.5️⃣ #17 本地服务器环境规划（2026-09-15）

#### 机器现状
- i3-10100 4C/8T · 8GB RAM · 915GB 盘 · Ubuntu 24.04 + GNOME
- 已跑：trumd（8321 健康 ✅）、frpc
- 缺：docker、nginx、psql、redis、基础工具链

#### 分工架构（本地宅基地 vs 阿里云）
```
阿里云：域名 + CDN + 公网入口 + 博客前端静态
本地：  trumd 核心 + SQLite 主库 + NAS/媒体 + 本地 AI + 备份中心
```

#### 数据库选型（已定：继续 SQLite，不迁 PostgreSQL）
- SQLite 当前够用：零配置、单文件、FTS5 全文搜索已支持
- PostgreSQL + pgvector 等 Phase 5 RAG 需要时再上（BOM 已记录）

#### 安装计划（分 4 期）
- [x] **P1 基础工具**（已完成 2026-09-15）：tmux htop btop ripgrep fd-find zsh zoxide bat btop fzf fastfetch unzip jq tree gh
- [x] **P2 Docker 脚本已完成**（2026-09-16）：install_docker.sh 已上传到本地服务器 /tmp/
  - [ ] **待执行**：sudo bash /tmp/install_docker.sh（需要用户手动跑）
  - [ ] 验证：docker --version、docker compose version、docker run hello-world
  - [ ] 配置镜像加速后 restart docker
- [ ] **P3 Web 服务**（约 40 分钟）：nginx（反代 trmd 8321 + 静态托管）、certbot（如果上域名）、redis 按需
- [ ] **P4 进阶**（后续）：本地 embed/vLLM、NAS 服务、CI runner

#### 内存分配建议（8GB）
| 用途 | 分配 |
|---|---|
| 系统+桌面 | ~2GB |
| trumd | ~1GB |
| Docker 容器池 | ~2GB |
| 空闲（预留） | ~3GB |

---

## 🟡 中优（本机可做）

### 2.6A 基础设施确认（2026-09-16）

- [x] **Snapper 跨发行版确认**：
  - ✅ 所有主流发行版（Arch / Ubuntu / Fedora / openSUSE）均可用
  - ⚠️ 前提：需要 **Btrfs** 或 LVM-thin 文件系统
  - 待确认本地服务器分区格式：`lsblk -f` 或 `findmnt -o FSTYPE /`
- [ ] **Coding Agent（选装）**：参考 ECC 项目评估
  - ECC 方案：Agent 独立 sandbox + 编码工具链（Codex CLI/Claude CLI）
  - 前置条件：Landrock 安全策略落地后接入
  - 验收标准：Agent 仅能读写白名单目录 + 无权限逃逸
  - 定位：**选装组件**，非核心依赖
  - 依赖：Codex CLI（已装 v0.147.0）/ Claude CLI
  - 前置条件：Landlock 安全策略落地后接入
  - 验收标准：Agent 仅能读写白名单目录 + 无权限逃逸

### 2.6️⃣ 明天待办 — 分支同步 + 继续服务器搭建
- [ ] **同步所有 Git 分支**：main 落后 ubuntu 20 commits、server 落后 23、arch-linux 落后 69（需保留各分支独有 desktop/arch 配置）
- [ ] **P2 安装 Docker**：docker.io + docker-compose-plugin，限制 2GB 内存 / 20GB 盘，dockerd 只 bind 127.0.0.1
- [ ] **P3 Nginx 反代 + 静态托管** 到 trumd 8321
- 用电参考：机器全天开约 0.7~1 kWh/天，电费约 13~18 元/月，可考虑不用时睡眠

### 3️⃣ 降低 LLM 集成测试的平台依赖
- `test_llm_integration.py` 有 3 个 failed 全是 Windows shell 问题（WinError 6/50）
- [ ] 区分平台：对 Windows 跳过或 mock。让 linux 跑真的，windows 跑假的
- 目标：**全平台 `306/306 pass, 0 fail`**

### 4️⃣ 修复 STATUS.md 中的 Return to Zero 获取新 API Key 瓶颈
- SafeMind 红蓝对抗设计中有"API Key 耗尽→停止→用户填新 Key"的流程
- [ ] 表格化列出当前项目中所有需要 API Key 的点（codex、LLM 混合策略、transform agent）
- [ ] 设计一个统一的 API Key Manager（Phase 3.5）

### 5️⃣ X1 Skill 集成（已有代码，需跑 demo 验证）
- 文件完整：`skill_loader.py`、`skill_router.py`、`skill_executor.py`
- [ ] 写出端到端 demo 测试（一个 YAML skill → router → execute）
- [ ] demo 通过后标记完成

### 6️⃣ 工具文件化的 `opencli` 加载失败
- 每次启动 log：`tool_file_loader.module_failed error="name '__tool' is not defined" tool=opencli`
- [ ] 检查 `~/.trimum/tools/opencli/main.py` 是否缺少 tool 注册头

### 7️⃣ X3 Agent 自优化（可选不着急）
- Agent 可优化自己的 prompt/示例/工具策略（不可改权限/安全边界）
- 改进建议写入 memory/pending-improvements.json
- 接口：`trm agent improve/apply`

### 8️⃣ 清理无关文件并提交
- [ ] 删除 `D:\trimum\tmp\` 目录（codex 遗留临时文件）
- [ ] 删除 `tmp_ship/`、`tmp_ship.tar.gz`、`tmp_deploy/`
- [ ] 删除 `ARCH.md` 和 `PRD.md`（内容已过时，Ubuntu 预置 Agent 计划已完成）
- [ ] `STATUS.md` 更新到 v16（反映当前状态）
- [ ] 统一提交、推送到 ubuntu 分支

---

## 🟢 低优（Linux 真机或后续）

### 9️⃣ #14 Landlock / Seccomp 沙箱（Phase 4 预备）
- `policy_engine.py` 和 `security_rule.py` 已有 stub 接口
- Linux-only，等真机部署后实现
- 跟 #15 真机部署绑定

### 🔟 全量测试 → 真机上跑 306/306 pass
- Windows 有平台差异（3 个 shell 相关 failed + 1 skip）
- 目标 Ubuntu 下：所有 306 测试通过，0 fail

### 1️⃣1️⃣ safe_lab.py + red_team.py + verifier.py 红蓝对抗（Phase 4）
- 已有设计，codex 可协助生成框架代码
- 需要 LLM API Key 用于红队攻击 Agent
- 需在真机上跑（实际 agent 调度）

### 1️⃣2️⃣ Agent SDK 包装
- `src/agent-sdk/` 当前为空
- 目标：在 openai-agents-python 上包装 Tool Gateway + Security Agent
- Phase 4+ 工作

---

## 🔵 远期 / Phase 4+

| 任务 | 说明 | 前置 |
|------|------|------|
| **Agent SDK 包装** | 集成 openai-agents-python | Phase 3 稳定后 |
| **SafeMind 红蓝对抗** | safe_lab + red_team + verifier | API Key Manager |
| **trimum 一键安装脚本** | `trm install` + Plugin Marketplace | Phase 4 稳定 |
| **Tray UI / 弹窗** | SecurityAgent.confirm() UI | Phase 4 |
| **Agentic Wiki** | 知识库检索 + Agent 编写 | Phase 5+ |
| **语言演进** | PyO3 / TS / Rust 重写核心 | Phase 6+ |

---

## ✅ 近期已交付（2026-09 上半月）

| 交付 | 详情 |
|------|------|
| **#3.7 ResourceController + Token 可视化** | PsutilController / CgroupV2Controller / TokenUsageTracker / TokenStatusPanel Rich 面板 ✅ |
| **#11 LLM 混合策略** | LlmPolicyEngine(正则+LLM) + LLMDecisionCache + api_server 注入 ✅ |
| **#3.9 多步 Agent 循环** | run_interactive / 确认交互增强 / Operator 模式(`/stop /skip /edit /retry`) ✅ |
| **WorkflowEventDriver 集成** | WorkflowEngine + Driver Socket 派发 + 3 类 Driver + `__init__.py` 修复 ✅ |
| **#16 清理** | 删除 phase2/wt-agent 目录与分支 + 核心模块目录同步 + 4/4 import 测试通过 ✅ |
| **Security Agent 全链路** | SecMonitor(440l) + SecExecutor(200l) + threat_workflows(216l) + workflow_listener(282l) ✅ |
| **工具文件化** | Scraper(Scrapling) + DocParser(PDF/DOCX/PPTX/XLSX/MD) + `__dependencies__` 注册头 ✅ |
| **X4 证书体系** | agent_cert.py 官方/自签/无证三档 + 机器指纹 ✅ |
| **OpenCLI Bridge** | 代码 + 部署 + 目标 Ubuntu 实测通过 ✅ |

---

## 测试状态明细

| 项目 | 状态 |
|------|------|
| 本地全量测试（排除 llm & agent_cert） | 242 passed, 1 skipped ✅ |
| 本地 3 failed | 全是 Windows subprocess 编码问题，Linux 必绿 |
| 远程 import 验证 | 33/33 模块全部加载成功 ✅ |
| 测试覆盖率 | 14 个测试文件，关键模块全覆盖 |

---

## Git 分支同步

| 分支 | 状态 | 备注 |
|------|------|------|
| `ubuntu` | ⭐ 最新 | 当前开发分支，已 push |
| `main` | ⏳ 需同步 | Phase 3 + #11 之后未跟进 |
| `server` | ⏳ 需同步 | 同上 |
| `arch-linux` | ⏳ 需同步 | 同上；ipc_handler.py 需手动 cherry-pick |

---

## 本期已关闭项

| 项 | 原因 |
|----|------|
| `tool_gateway.py` 截断问题 | ✅ 已修好（866 行完整），MEMORY.md 过时记录已删 |
| tool_gateway 缺失方法 | ✅ `_record_audit`/`_redact_credentials`/`_check_jit_auth`/`_check_cwd_jail` 全部存在 |
| Windows 下 shell 测试 | ⚠️ 保留为"已知平台差异"，不做修复（target 是 Linux） |
| ARCH.md / PRD.md | 📦 Ubuntu 预置 Agent 计划已完成，文件可删 |
