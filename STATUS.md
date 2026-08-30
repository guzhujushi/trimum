# STATUS — 当前进度

> 最后更新：2026-08-30（v8 — 集成 Omarchy 主题资源，Phase 1.5 主题资产就绪）
>
> 当前阶段：Phase 1.5 启动（AI Shell MVP 完成；Omarchy 主题/参考资产已集成）

---

## 任务清单

### Phase 0 — 基础环境建设
- [x] 项目 README（定位、架构、路线图）
- [x] 架构文档（ARCHITECTURE.md v2.0）
- [x] 开发路线解读（DEVELOPMENT-ROADMAP.md）
- [x] 技术选型 BOM（TECHNICAL-BOM.md）
- [x] 参考项目调研（REFERENCE-PROJECTS.md）
- [x] 开源复用策略（REUSE-STRATEGY.md v2）
- [x] 配置文件骨架（config/trimum.yaml, config/policy.yaml）
- [x] Phase 1 详细开发计划（docs/PHASE1-PLAN.md）
- [x] STATUS.md 三文件工作流就绪 + 密钥配置写入 README
- [x] AGENTS.md 更新（API 频率限制 + 代理配置）
- [x] 项目名定稿：trimum（CLI 命令 trm）
- [x] 开发环境方案变更：放弃虚拟机，Phase 1 直接在 Windows 开发

### Phase 1 — AI Shell MVP（Python）
- [x] 第 1 步：项目脚手架 + LLM 适配器（L-1/L-8 已修复）
- [x] 第 2 步：策略引擎 + 配置（C-1/C-2/M-1/M-6/L-4 已修复）
- [x] 第 3 步：命令规划器（H-2/M-3 已修复）
- [x] 第 4 步：执行器 + 确认流程（H-1/M-2/L-5/L-6/L-9 已修复）
- [x] 第 5 步：CLI 入口 + 输出格式化（M-4/L-2/L-3/L-7 已修复）
- [x] 第 6 步：Shell 集成（desktop/zsh-ai.sh + desktop/ai.ps1）
- [x] 第 7 步：验证（test_scenarios.py，39 个用例全部通过）
- [x] 代码审查（2026-08-30）：结论见 tmp/code-review-findings.md；修复总结见 tmp/phase1-fix-summary.md

### Phase 1.5 — 桌面预设 + 安装脚本
- [x] 集成 Omarchy 主题资源（22 套 → desktop/themes/）+ Snapper 脚本 + 参考文件（docs/omarchy-ref/），摘要见 tmp/omarchy-integrate-summary.md
- [ ] 评估 Omarchy 的 Hyprland 预设能否复用
- [ ] Hyprland 预设主题包（7 套）
- [ ] Btrfs + Snapper 自动配置
- [ ] 安装脚本 — 基于 pyinfra

### Phase 2 — trimum Core（Python + FastAPI）
- [ ] API Server 框架 + Tool Gateway
- [ ] Policy Engine + Agent Manager（Supervisor）
- [ ] Event Bus + Context Manager（SQLite，atuin Schema）
- [ ] Unix Socket / HTTP 接口

### Phase 3 — Agent SDK
- [ ] pip install openai-agents + apprise + psutil
- [ ] 自定义 Tool + Guardrail
- [ ] 预设 Agent + explain / fix 管道

### Phase 4 — Security Runtime
### Phase 5 — Memory Layer（chroma 替代 PostgreSQL）
### Phase 6 — ISO / 安装镜像

---

## 决策记录

| 日期 | 决策 | 理由 |
|---|---|---|
| 2026-08-29 | Phase 2 改用 Python + FastAPI，放弃 Rust | Rust 编译卡关是 vibe coding 最大风险 |
| 2026-08-29 | 全项目 Python 主栈 | 统一语言栈降低维护成本 |
| 2026-08-29 | 引入 openai-agents-python | 替代自研 Agent SDK |
| 2026-08-29 | 引入 Supervisor / psutil / apprise / chroma | 替代自研进程管理/系统度量/通知/向量库 |
| 2026-08-29 | Phase 5 用 chroma 替代 PostgreSQL+pgvector | 桌面场景不需要服务级数据库 |
| 2026-08-30 | 项目名定稿：trimum / trm | 原名 Harness 太土，改为 trimum |
| 2026-08-30 | 放弃虚拟机，Phase 1 直接在 Windows 开发 | AI Shell 核心逻辑（LM调用+subprocess+策略引擎）完全跨平台，在 Windows 上写好验证后再部署 Linux |
| 2026-08-30 | Phase 1 审查问题全部修复（C-1/C-2/H-1/H-2/M-1~M-6/L-1~L-9） | 策略规范化（normalize_command 拆段）+ 磁盘工具规则补全 + GBK 安全符号 + 包重构 trimum_mvp/ + Step 6/7 补齐 |
| 2026-08-30 | M-5 包重构：6 个模块迁入 trimum_mvp/ 包 | 顶层通用模块名（cli/policy 等）避免污染 site-packages；trm 入口改为 trimum_mvp.cli:app |

---

## 今日进度（2026-08-30）
| 完成项 | 状态 | 备注 |
|---|---|---|
| 项目名替换 + 遗留 bug 修复 | ✅ | trimum/trm 全部替换，4 处修改 |
| 密钥管理方案定稿并写入 README | ✅ | ~/.trimum/env + get_secret() SDK |
| 代理配置写入 AGENTS.md | ✅ | Clash 127.0.0.1:7993 |
| 尝试搭建 Arch 开发虚拟机 | ❌ | GRUB 引导失败 + osboxes 兼容问题，决定放弃 |
| 开发环境方案变更 | ✅ | Phase 1 全部在 Windows 开发 |
| 三文件工作流补全（PRD.md / ARCH.md） | ✅ | 补齐缺失文档 |
| Phase 1 编码 + 审查修复（src/trimum-mvp） | ✅ | 第 1~7 步全部完成，39 个测试用例通过 |
| Phase 1 代码审查 | ✅ | 详见 tmp/code-review-findings.md（2 critical / 3 high / 6 medium / 9 low） |
| 集成 Omarchy 资产（22 套主题 + snapper + 参考文件） | ✅ | 256 文件 / ~63 MiB；22/22 主题含 colors.toml + 背景；摘要见 tmp/omarchy-integrate-summary.md |

---

## 下一步
0. 基于 desktop/themes/ 与 docs/omarchy-ref/ 评估 Omarchy 预设复用方案，产出 Hyprland 主题包（7 套）与 Btrfs+Snapper 安装脚本
1. 在真实 Windows 终端安装验证：`pip install -e src/trimum-mvp --no-build-isolation`（本沙箱禁止 python 写工作区/站点目录，未执行安装）
2. 配置真实 API Key（TRIMUM_API_KEY）后运行 `trm "查看磁盘空间"` 等场景实测 LLM 链路
3. Linux/Arch 部署推迟到 Phase 1 验收后，用二手小主机或 VPS
