# DeepSeek 建议审核报告

> 创建：2026-09-02
> 来源：对 DeepSeek 交给 trimum 建议的再分析（`D:\trimum\建议.md`）
> 审核人：孤竹居士 trimum Core Team

---

## 审核结论

DeepSeek 本次建议整体方向正确——强化了 trimum "AI Runtime Layer，不是 Linux 发行版"的核心定位。以下是逐条分析。

---

## ✅ 强烈采纳（3 项）

### 1. Transform Agent 增加 confidence 字段

**思路**：TARL intent 中增加 `confidence:` 字段，低于阈值（如 `< 0.7`）触发澄清。

**为什么采纳**：
- trimum 定位是"安全 AI Runtime"，"知道自己不知道"是核心能力
- 普通 AI 最大问题：它不知道自己不知道。这是差异化的关键点
- 类似自动驾驶：不是"永远执行"，而是"我有多少把握"

**入文件**：
- `docs/TARL-SPEC.md` — 在 intent 块中增加 `confidence` 字段定义
- `transform_agent.py` — 输出时携带 confidence，低于阈值转澄清流程

**优先级**：🟡 #12 弹性沙箱完成后做

---

### 2. TRM 错误码体系

**思路**：类似 Linux errno / Docker exit code / Kubernetes status.reason 的三段式错误码。

| 范围 | 含义 | 示例 |
|---|---|---|
| TRM-1xxx | Runtime 错误 | TRM-1001 Agent 启动失败 |
| TRM-2xxx | Security 错误 | TRM-2001 权限拒绝 |
| TRM-3xxx | Agent 错误 | TRM-3001 推理超时 |
| TRM-4xxx | Tool 错误 | TRM-4001 工具执行失败 |

**为什么采纳**：
- 为未来生态打好基础
- 当前架构已有结构化的错误处理机制（Task State Machine 的 TIMEOUT/BLOCKED/FAILED），但未统一错误码
- 与 Task State Machine 天然互补：状态 + 错误码 = 完整的异常上下文

**入文件**：
- 新建 `docs/ERROR-CODE-SPEC.md`
- `models.py` 增加 `TrimumError(Exception)` + 错误码协议

**优先级**：🟢 低优，Phase 3/4 交接时做

---

### 3. Policy Engine 学习模式

**思路**：Security Agent + Behavior Monitor 观察用户行为 → 动态生成 allow ruleset → 新人严格模式、老司机自动化模式。

**为什么采纳**：
- 当前 Behavior Monitor 已经实现了操作历史追踪和异常检测（滑动窗口 300s，8 大类 22 小类）
- 下一步自然延伸就是"把模式观察转化为 Policy Engine 的规则自动更新"
- 完全吻合 trimum "安全 AI Runtime + Linux 权限 + AI 学习"的定位

**入文件**：
- `STATUS.md` — 将"Policy Engine 学习模式"加入 TODO，与 Behavior Monitor 形成 pipeline

**优先级**：🟡 #9-#13 弹性沙箱集成过程中纳入 scope

---

## ⚠️ 部分采纳（3 项）

### 4. Event Bus 虚拟文件接口

**思路**：不 FUSE，但保留 `/run/trimum/events/` 的文件接口作为 Event Bus 的可选展示层。

**为什么部分采纳**：
- 当前 Event Bus 已完成异步 pub/sub 架构，不需要文件系统接口做核心
- 但作为未来 IPC 接口层的补充，`/run/trimum/events/` 的目录设计值得保留
- 类似 /proc、/sys：不是它们存状态，而是展示接口

**入文件**：
- `docs/ARCHITECTURE.md` — 在 Event Bus 章节增加"可选的虚拟文件接口（Phase 3+/4）"段
- 不作当前开发项

**优先级**：🔵 远期参考（Phase 4+）

---

### 5. Memory Layer 渐进方案（SQLite → sqlite-vec）

**思路**：MVP 用 SQLite 存 key-value 记忆 → 后期需要语义搜索时引入 sqlite-vec → 最后才考虑专用向量库。

**采纳部分**：
- ✅ "不要一开始做 Embedding"的判断正确——trimum Memory 核心是"找用户历史/偏好/ workflow"，不是"找相似文章"
- ✅ "不要让 Memory 污染 Agent"（Memory Tool 返回 5 条相关信息，不全部加载）——施工中已做到（Agent 私有 / 项目共享 / 全局三重分离）

**暂不采纳部分**：
- 当前已决策 Phase 5 用 chroma（2026-08-29 决策），理由是"桌面场景不需要服务级数据库"
- chroma 比 sqlite-vec 重但比专业向量库轻，这个决策不出大问题前不变

**入文件**：
- `docs/ARCHITECTURE.md` — 在 Memory 章节增加渐进路线注释，作为 future option

**优先级**：🔵 知识记录，不改变当前 Phase 5 计划

---

### 6. 采纳方案架构图调整

文件建议的：
```
Harness Core = Event Bus + Agent Runtime + Tool Gateway + Policy Engine + Error System + IPC Interface
```

当前的状态 (Phase 3) 实际上已是这个结构。验收通过，架构无需调整。

---

## ❌ 不采纳（2 项）

### 7. usearch 推荐

**原因**：usearch 解决 100 万+ 向量搜索，trimum 当前和可见未来的数据量都不匹配这个规模。与上面 Memory 建议矛盾——既然主张"不要一开始做 Embedding"，又推荐 usearch 是逻辑不自洽。

### 8. 大规模 Agent Marketplace

文件自己也在"暂时不要加入"清单里。确认不需要。

---

## 📋 关键校正

DeepSeek 的分析有一个重要的隐性确认：**trimum 当前定位与方向正确**。

这次检查发现：
- 建议中的错误码体系、confidence、Policy 学习，在 trimum 当前架构里**没有任何冲突或矛盾**
- DeepSeek 没有发现"被忽略的重大 Blind Spot"——最大价值是给了未来扩展的语料参考
- 核心建议（不要造 Linux 发行版，要做 AI Runtime Layer）和 trimum Phase 3 的定位一致

---

## 操作清单

| # | 动作 | 优先级 | 责任人 |
|---|---|---|---|
| 1 | 新增 `docs/ERROR-CODE-SPEC.md` — 定义 TRM 错误码规范 | 🟢 低优 | 孤竹 |
| 2 | 修改 `docs/TARL-SPEC.md` — intent 增加 `confidence` 字段 | 🟡 集成阶段 | 孤竹 |
| 3 | 修改 `docs/ARCHITECTURE.md` — Event Bus 增加虚拟文件接口注释 | 🔵 远期 | 孤竹 |
| 4 | 修改 `docs/ARCHITECTURE.md` — Memory 增加渐进路线注释 | 🔵 知识 | 孤竹 |
| 5 | `STATUS.md` — 将"Policy Engine 学习模式"写入下一步 | 🟡 | 孤竹 |
| 6 | 删除 `D:\trimum\建议.md`（内容已入档） | ✅ | 孤竹 |
