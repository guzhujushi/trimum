# PRD — trimum（AI 原生 Arch Linux 桌面运行时）

## 产品目标
- 提供一个以 Arch Linux 为底座、Hyprland 为桌面的 AI 原生桌面环境。
- 让用户通过自然语言完成系统操作、维护与故障排查（AI Shell）。
- 本期（Phase 1）目标：实现 `trm` 命令行 MVP——自然语言 → 命令 → 安全执行 → 输出的完整闭环。

## 功能需求
1. **自然语言转命令**：用户输入中文/英文描述，AI 生成结构化命令计划（含步骤说明、命令列表、风险级别）。
2. **安全策略引擎**：基于 YAML 规则（shellfirm 风格）对命令做风险分级：low / medium / high / critical。
   - low → 自动执行；medium → 用户确认；high → 确认 + 警告并记录审计；critical → 直接拒绝。
3. **确认交互**：3 步确认 UI（展示计划 → 展示风险级别 → 询问 Continue? [y/N]）。
4. **管道输入**：支持 `cat log | trm "解释报错"` 的 stdin 输入模式。
5. **多模型适配**：OpenAI 兼容 API，支持自定义 base_url（DeepSeek 等国产模型），默认模型 deepseek-chat。
6. **Shell 集成**：`desktop/zsh-ai.sh` 提供 `ai()` 函数；Windows 侧提供 `desktop/ai.ps1` 便于本地开发验证。

## 用户场景
- 用户输入 `trm "查看磁盘空间"` → 低风险，自动执行 `df -h` 并展示结果。
- 用户输入 `trm "删除 /tmp 缓存"` → 中风险，确认后执行。
- 用户输入 `trm "删除系统日志"` → 高风险，确认 + 警告并记录审计日志。
- 用户输入 `trm "格式化磁盘"` → 关键风险，直接拒绝并提示。
- `cat config.py | trm "解释这段代码"` → 管道内容作为上下文输入，AI 解释而不执行命令。

## 验收标准
1. `trm "查看磁盘"` 能输出磁盘使用信息（低风险自动执行）。
2. 低风险自动执行、中风险需确认、高风险拒绝或强确认、关键风险被拒绝。
3. `policy.yaml` 支持自定义规则（正则匹配风险级别 + 动作）。
4. `ai()` Shell 入口函数可用，管道输入模式可用。
5. `test_scenarios.py` 中 5 个典型场景全部通过（LLM 调用被 mock）。

## 范围边界
- 本期只做 CLI MVP（Python），不做 daemon、Agent SDK、桌面端 UI。
- 先在 Windows 上开发验证，Linux/Arch 部署推迟到 Phase 1 验收后。
- 不引入 sandbox 容器隔离（Phase 2+ 再考虑）。
- API Key 只从环境变量读取，不写入代码或配置文件。