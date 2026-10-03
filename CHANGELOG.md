# Changelog

本项目所有值得注意的变更都记录在此文件。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循语义化版本。

## v0.5.0 — 2026-10-03

### Added
- 纯 Python 的 Linux AI Agent 运行基础设施（Harness）：常驻 daemon + 可插拔 Agent + 统一 Tool Gateway + Workflow 引擎 + EventBus；安全栈含 Landlock + seccomp + bwrap userns + cgroup 限额 + 审计哈希链（带外见证），并支持 MCP 接入、记忆分类索引与 CLI（`trm`）（本公开版为脱敏精简快照，不含桌面配置）
- 脚本：博客好友 → Gitea 同步（默认 dry-run，`--apply` 才建号）
- 运维脚本：`fix_codex_ext_sandbox.sh`（给 VS Code Codex 扩展自带 bwrap 补 AppArmor profile）、`setup_gitea_mailer.sh`、`gitea_gen_token.sh`

### Changed
- 默认包目录改指 `<TRIMUM_HOME>/packages/index.json5`（本地优先）
- 测试：7 条 skill 集成用例改用 tmp skills fixture 并解除宿主依赖 skip；14 条宿主环境依赖用例显式 skip 并留理由
- 文档：沙箱计划补第 8 个 spawn 点实锤结论，并清理 TaskRegistry 旧名

### Fixed
- `agent_launcher`：`launch.error` 且 process 为 None 时不再访问 `process.pid`
- `mcp`：`MCPServerDefinition` 拒绝未知键（`extra=forbid`）
- `sandbox`：`validate_scope` 跳过路径文案去掉多余空格

### Removed
- （本版本无移除项）
