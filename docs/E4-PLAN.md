# E4 计划 — 广接入（通用 CLI 适配器 + workflow 目录 + 导入器）

> 立项：2026-09-20（`docs/ECOSYSTEM-STRATEGY.md` §5 的 E4；缺口表第 4 / 6 / 7 项）
> 顺带：E3 顺延的 `trm skill import`（技能层唯一的空口）
> 原则不变：**做生态集成器，不做生态复制品** —— 生态的东西都从这里进来，但一律落到
> 「同一张表 + 同一套策略 + 同一份审计」，第三方默认**不启用**。

## 1. 目标与验收

| 交付 | 验收（可执行） |
|---|---|
| 通用 CLI 适配器（缺口 #4） | `trm tool import-cli <binary> --dry-run` 给出工具条目 + **风险分级理由**；真导入后 `<trimum_home>/tools/<name>/` 有 `tool.json5` + `main.py`，默认 `enabled: false` |
| workflow 目录（缺口 #6） | `trm workflow import <path\|repo> --dry-run` 逐条给出校验结果；导入后 `trm workflow list` 能列出 |
| 生态统一 schema（缺口 #7） | 三类导入产物都带 `trust` / `risk` / `requires` / `source_url` / `author` / `origin`；缺字段可校验 |
| `trm skill import`（E3 顺延） | `trm skill import <path\|repo> --dry-run` 列技能与目标位置；导入后 `trm skill list` 能看到 |

红线（沿用 E3 的写法，写进代码与测试）：

1. **导入不执行**：适配器只跑 `--help` 这类只读探测；workflow / skill 导入只读文本、只写文本，**绝不 import、绝不执行**导入物。
2. **`--dry-run` 不落盘**：三个导入器共用同一条规则，测试逐条断言「目标目录没有任何新增」。
3. **非交互要 `--yes`**：与 `env` / `mcp` / `install` 一致（非 TTY 直接 abort）。
4. **第三方默认不启用**：写出的工具 manifest 是 `enabled: false`，要 `--enable` 或事后 `trm tool enable <name>` 才进注册表。
5. **不覆盖已有**：目标已存在时拒绝，除非 `--force`（且 `--force` 只在显式给出时生效）。
6. **不引入新依赖**：YAML 用已有 PyYAML；git 源走系统 `git clone --depth 1`，失败即报错，不做静默降级。

## 2. 设计

### 2.1 模块

| 模块 | 职责 |
|---|---|
| `src/trimum_core/ecosystem.py` | 生态条目 schema：`trust` / `risk` / `requires` / `source_url` / `author` / `origin` / `enabled` + **风险分级器**（动词表 + 理由）+ 校验器 |
| `src/trimum_core/cli_adapter.py` | 通用 CLI 适配器：探测 `--help` → 解析子命令/旗标 → 定级 → 生成 `tool.json5` + `main.py`；并提供生成的 `main.py` 用的通用执行器 |
| `src/trimum_core/workflow_catalog.py` | Warp 式 workflow 目录格式（`name` / `command` / `steps` / `tags` / `arguments` / `risk` / `requires`）+ 编译到 `WorkflowDefV2` |
| `src/trimum_core/skill_import.py` | 技能导入：源解析（本地路径 / git URL）→ 找 `SKILL.md` → 校验 frontmatter → 复制进 `~/.trimum/skills/` |
| `src/trimum_core/tool_file_loader.py`（改） | manifest 支持 `enabled`（缺省 true，兼容既有工具）；`scan_tools(include_disabled=)` |
| `cli/commands/{tool,workflow,skill}.py`（改） | 三组新子命令 + `__command_meta__` |

### 2.2 风险分级（`ecosystem.assess_risk`）

输入：二进制名 + 子命令名 + 旗标。规则**可解释**（每条理由都进 dry-run 输出）：

| 级别 | 触发 |
|---|---|
| `critical` | 出现破坏性形态：`mkfs` / `dd if=` / `shutdown` / `reboot` / `rm -rf /` |
| `high` | 变更系统或不可逆：`install` / `remove` / `purge` / `delete` / `rm` / `kill` / `prune` / `format` / `push` / `publish` / `deploy` / `sudo` |
| `medium` | 有副作用但不破坏：`run` / `start` / `create` / `set` / `update` / `sync` / `pull` / `clone` / `apply`；或 `--force` / `-y` 这类"免确认"旗标 |
| `low` | 纯读：`list` / `show` / `status` / `info` / `log` / `version` / `read` / `search` / `diff` / `check` |
| 兜底 `medium` | 无任何证据 —— **不猜低**（猜低会让第三方命令悄悄变成低风险），也不夸大成 high |

### 2.3 通用 CLI 适配器产物

```
<TRIMUM_HOME>/tools/<name>/
├── tool.json5     # name/kind=custom/risk/timeout/allowed_flags + 生态元数据（trust/requires/source_url/author/enabled）
└── main.py        # 生成的薄壳：from trimum_core.cli_adapter import generic_executor
```

- 生成物**只是薄壳**，真正的执行逻辑在 `cli_adapter.generic_executor`（可单独单测）；
- `generic_executor` 自己再兜一层：子命令必须在探测到的集合里、旗标必须在 `allowed_flags` 里、
  二进制用 `shutil.which` 解析（不信任 manifest 里的路径）—— 即便有人手改 manifest 也过不了这一层；
- 探测输出的子命令数有上限（默认 12），避免 `git` / `apt` 这类巨型 CLI 把导入变成扫描。

### 2.4 workflow 目录格式（低摩擦入口）

```yaml
id: docker-cleanup            # 可选，缺省取文件名
name: Docker 清理
description: 清掉悬空镜像与停止的容器
tags: [docker, cleanup]
risk: medium
requires: [docker]
command: docker system prune -f          # 单命令写法
# 或
steps:
  - run: docker ps
  - run: docker system prune -f
author: someone
source_url: https://github.com/xxx/trimum-workflows
```

编译规则：`command` / `steps[].run` → `WorkflowDefV2.steps[].execute[]`（`agent_type: shell`，`instruction` 原文）；
导入落点 `~/.trimum/workflows/<id>/workflow.yaml`（`WorkflowDefV2.load_from_dir` 既有的布局）。

### 2.5 信任与启用

- 导入产物写 `trust`：CLI 适配器默认 `third-party`，可 `--trust official|curated|third-party|local`；
- **注册 ≠ 授权**：`enabled: false` 只是不进 `ToolRegistry`；即便启用了，运行时仍走
  ToolGateway 六层 + SecurityRule + 审计（E4 不改这一层）；
- `trm tool enable|disable <name>` 只翻转 manifest 的一个布尔值，不做别的。

## 3. 切分与顺序

| 片 | 内容 | 依赖 |
|---|---|---|
| S1 | `ecosystem.py` + 测试（分级器 / 校验器） | — |
| S2 | `cli_adapter.py` + `trm tool import-cli` / `enable` / `disable` + 测试 | S1 |
| S3 | `workflow_catalog.py` + `trm workflow import` + 测试 | S1 |
| S4 | `skill_import.py` + `trm skill import` + 测试 | — |
| S5 | `tool_file_loader.enabled` + `trm tool list --all` + 测试 | S2 |
| S6 | 文档（ARCH / TODO / STATUS / ECOSYSTEM-STRATEGY 缺口表 / OPERATIONS） | S1-S5 |
| S7 | 真机验证（开发树跑导入 dry-run + 真导入一个本地 fixture）+ 提交 | S6 |

## 4. 测试计划

- `tests/test_ecosystem.py`：分级器（各级别用例 + 兜底 + 理由可读）、校验器（缺字段 / 非法 trust / 非法 risk）、序列化。
- `tests/test_cli_adapter.py`：`parse_help`（三种真实 `--help` 形态：`Commands:` 段、`命令：` 段、无子命令）、
  探测（假 runner，不依赖真二进制）、`generic_executor`（旗标白名单 / 子命令白名单 / which 失败 / 超时）、
  导入落盘（dry-run 不落盘 / 默认 disabled / `--force` 语义 / 已存在拒绝）。
- `tests/test_workflow_catalog.py`：格式解析（单命令 / steps / 缺 name / 非法 risk / 未知字段）、
  编译到 `WorkflowDefV2`、导入落盘与 `load_from_dir` 往返、dry-run 不落盘。
- `tests/test_skill_import.py`：本地目录 / 多技能目录 / git URL（假 git runner）、frontmatter 校验、
  重名拒绝与 `--force`、dry-run 不落盘。

## 5. 已知取舍

1. **不做 `--help` 的语义理解**：解析是启发式的，解析不到子命令就不写（而不是编一个）。宁可少登记。
2. **不做「CLI 适配器自动接进 ToolGateway 分发器」**：生成的工具走既有 `main.py` 契约，不新增 ToolType。
3. **不做 workflow 的远程目录**：`import` 只接受本地路径或 git URL，不做「订阅/自动更新」（那是 E5 官方渠道的事）。
4. **skill 导入不做依赖解析**：只搬文件 + 校验 frontmatter；技能之间的引用留给后续。
