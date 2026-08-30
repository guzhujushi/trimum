# Phase 1 — AI Shell MVP 开发计划

> 目标：实现 `trm "查看磁盘"` 自然语言 -> 命令 -> 安全执行 -> 输出 的完整闭环。
> 语言：Python，跨平台（先在 Windows 上跑通，再部署到 Arch 验证）。
> 预估周期：1.5 - 2 周（vibe coding 模式，利用开源复用策略）。

---

## 文件结构

```
src/trimum-mvp/
├── cli.py              # Typer 命令行入口（入口点：`trm "..."`）
├── llm.py              # LLM 适配器（参考 shell_gpt 适配器模式）
├── planner.py          # 命令规划器（自然语言 -> 命令列表 + 风险预估）
├── policy.py           # YAML 策略引擎（参考 shellfirm 配置格式）
├── executor.py         # 命令安全执行器（确认流程 + subprocess）
├── output.py           # 输出格式化（Rich）
├── config.yaml         # 默认配置文件
├── policy.yaml         # 权限规则文件
└── pyproject.toml      # 项目元数据和依赖

desktop/
└── zsh-ai.sh           # ai() Shell 入口函数（照搬 zsh-ai，改后端为本地 CLI）
```

---

## 任务拆解（按依赖顺序）

### 第 1 步：项目脚手架 + LLM 适配器
- [ ] 创建 `src/trimum-mvp/` 目录和 `pyproject.toml`（依赖：typer, rich, httpx, pyyaml）
- [ ] 复写 `llm.py`：shell_gpt 的 OpenAIClient 适配器模式，简化到 ~200 行
  - 支持自定义 base_url（国产模型兼容）
  - stream/non-stream 两种模式
  - 错误重试 + 友好报错

### 第 2 步：策略引擎 + 配置
- [ ] 复写 `policy.yaml`：shellfirm 格式，定义 low/medium/high/critical 三级风险
- [ ] 实现 `policy.py`：YAML 加载 + 正则匹配 + 返回风险级别/动作
- [ ] 默认规则覆盖：ls/cat/df/du（auto）、rm/chmod/chown（confirm）、rm -rf /（deny）

### 第 3 步：命令规划器
- [ ] 实现 `planner.py`：LLM 接收自然语言输入 -> 返回结构化命令计划
  - 格式：{plan: [...] , commands: [str], risk: "low|medium|high|critical"}
  - prompt 设计：角色设定 + 安全约束 + 输出格式约束

### 第 4 步：执行器 + 确认流程
- [ ] 实现 `executor.py`：
  - subprocess.run() 安全执行（含 timeout 限制）
  - 低风险：自动执行
  - 中风险：用户确认（y/N）
  - 高风险/拒绝：显示拒绝信息
- [ ] 3 步确认 UI（参考 shell_ai 交互流程 + Warp 设计理念）

### 第 5 步：CLI 入口 + 输出格式化
- [ ] 实现 `cli.py`：Typer 入口 `trm "自然语言描述"`
- [ ] 实现 `output.py`：Rich 格式化（错误红色、成功绿色、警告黄色）

### 第 6 步：Shell 集成
- [ ] 实现 `desktop/zsh-ai.sh`：ai() Shell 函数，后端调本地 trm
  - 支持管道输入：`cat log | ai "解释报错"`

### 第 7 步：验证
- [ ] 测试 5 个典型场景：
  1. `trm "查看磁盘空间"` 低风险，自动执行
  2. `trm "删除 /tmp 下的缓存"` 中风险，确认后执行
  3. `trm "删除系统日志"` 高风险，确认后仍警告
  4. `trm "格式化磁盘"` 高风险，拒绝
  5. `cat config.py | trm "解释这段代码"` 管道输入模式
- [ ] 在 Windows 上跑通测试场景
- [ ] 在 Arch 虚拟机中验证 Shell 集成

---

## 完成标准（Exit Criteria）

1. `trm "查看磁盘"` 能在终端输出磁盘使用信息
2. 低风险命令自动执行，中风险需确认，高风险被拒绝
3. policy.yaml 支持自定义规则
4. ai() Shell 入口函数可用
5. 管道输入模式可用
