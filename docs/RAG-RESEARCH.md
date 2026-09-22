# RAG 检索能力调研（2026-09-22）

> 定位：**E7（自研编码智能体）的前置能力调研**。结论：trimum 已有「关键词检索的记忆系统」，
> 但**没有语义检索**。RAG 在这里的正确形态不是「接一个 LangChain」，而是**给现有记忆层
> （ContextManager + MemoryClassifier）补一条语义检索通道 + 混合排序**。本文只调研、不改代码。

## 1. 现状：trimum 已经有什么（证据）

| 模块 | 职责 | 检索方式 |
|---|---|---|
| src/trimum_core/context_manager.py | SQLite 持久化 Agent 上下文（agent/project/global 三命名空间 + session 跟踪） | search() 走 **FTS5 虚拟表 context_fts**，unicode61 tokenizer，MATCH 关键词命中 |
| src/trimum_core/memory_classifier.py | 记忆分类层（domain/category 索引），独立 DB | query_by_domain / query_by_category + make_filter/matches **字段精确匹配**，无全文、无语义 |
| src/trimum_core/memory_bridge.py | Event Bus memory.* 事件 → ContextManager CRUD | 桥接，不含检索语义 |
| src/trimum_core/experience_learner.py | 监听 event.*.failed，调 LLM 分析失败，写结构化经验进 gent_memory/experience | **写入侧已用 LLM**，读回仍是关键词 |
| src/trimum_core/llm_router.py | LLM 一处策略（选谁 / 等多久 / 失败换谁） | 复用点：embedding 也走这里 |
| src/trimum_core/context_compactor.py | 上下文窗口管理（限长 + 滑窗 + 预算，**纯规则，不做 LLM 摘要**） | RAG 命中结果的「装进窗口」环节可复用 |

**关键判断**：
- 关键词检索（FTS5）能命中「出现过的字面」，但**命中不了同义改写**（"重启服务" vs "restart the daemon" vs "把进程拉起来"）。
- 对编码智能体，这正是最痛的场景：翻历史经验、翻项目约定、翻相似 bug 时，用户/agent 的措辞和当初存进去的措辞几乎必然不一致。
- 所以 **RAG 的收益点是「语义召回」，不是「再造一套存储」**——存储、命名空间、确认策略都已经有了，别重复造。

## 2. RAG 在这里要解决什么（按 trimum 的语境重述）

不是「文档问答机器人」那种 RAG，而是**Agent 的记忆/知识召回**：

1. **跨措辞召回**：按语义相似度找到"相关但字面不同"的历史经验 / 项目约定 / 失败教训。
2. **进上下文**：把 top-k 召回结果按 context_compactor 的预算装进当前 agent 的上下文窗口，喂给 LLM。
3. **不破坏安全边界**：召回只读，且要尊重现有「project_ctx/global_ctx 读需确认」的口径（memory_bridge.py 已定义）。

## 3. 三种落地形态对比（由轻到重）

| 方案 | 依赖 | 语义质量 | 离线可用 | 适配成本 | 备注 |
|---|---|---|---|---|---|
| **A. FTS5 增强**（BM25 + unicode61 调参 + 中文分词器） | 零新增 | 中（只懂字面同义，靠 BM25 权重） | ✅ 完全离线 | 极低 | 先把 FTS5 用起来（search() 已就绪，但调用方少）；中文需 porter2 之外的分词 |
| **B. 本地向量（embedding + 向量检索）** | 本地 embedding 模型（ONNX/sentence-transformers）+ sqlite-vec 或内存余弦 | 高 | ✅ 离线（模型本地） | 中 | **推荐主线**；embedding 走 llm_router，不新增网络依赖 |
| **C. 混合（B 向量 + A BM25，RRF 融合）** | B 的全部 + FTS5 | 最高 | ✅ 离线 | 中高 | **目标态**；RRF（Reciprocal Rank Fusion）免调参、对两路分数尺度不敏感 |
| D. 云 embedding API | 外部 API | 高 | ❌ 依赖网络 | 低 | 与 trimum「校园网/直连」约束冲突，**不推荐** |

**推荐路径：A → B → C**。A 当天可上（把 search() 真正接进 agent 记忆读取路径）；B 补语义；C 是稳态。

## 4. 向量层选型（B 方案）

- **存储**：sqlite-vec（官方 vec0 虚拟表，零额外服务、和现有 aiosqlite 同栈）—— 最贴合 trimum「单进程、非特权、无常驻依赖」的气质。备选：numpy 内存矩阵（库小时够用，重启重建）。
- **Embedding**：本地小模型，候选 ge-small / paraphrase-multilingual（中英双语，编码场景中文多）。**走 llm_router 的本地档**，不给 daemon 加外部网络。
- **切片**：记忆条目本身是**短结构**（key/value/namespace），不像长文档需要 chunking —— 一条一向量即可，省掉 chunker。这是 trimum 相比通用 RAG 的**天然简化**。
- **索引规模**：~/.trimum/ 下的记忆是**个人/项目级**（千~万条量级），余弦暴力扫都够，**不需要** FAISS/HNSW 那套重型 ANN —— YAGNI。

## 5. 与现有安全的衔接（不变量）

1. **只读召回**：RAG 只 SELECT，不写记忆；写入仍走 memory.* 事件桥（单一入口，已有审计）。
2. **确认口径不降级**：project_ctx/global_ctx 召回命中时，沿用 equires_confirmation/confirm_read，不因"搜到了"就自动放行读。
3. **命名空间隔离**：召回按 
amespace_filter（agent/project/global）走，和 search() 现有一致；跨 agent 的记忆不默认召回。
4. **可观测**：每次召回记录（query、top-k、分数、命中命名空间）进审计，便于调权重与排查"为什么召回了这条"。

## 6. 建议的下一步（若要立项，属 E7 前切片，非本轮）

- **切片 R1（≈半天，低风险）**：把 ContextManager.search()（FTS5）真正接进 agent 记忆读取路径 + 补中文分词；**纯 A 方案，零新依赖，先拿到"关键词召回可用"的正反馈**。
- **切片 R2**：加 sqlite-vec + 本地 embedding（走 llm_router 本地档），gent_memory 先试点；一条一向量、暴力余弦。
- **切片 R3**：BM25 + 向量两路 RRF 融合 + 召回结果经 context_compactor 装窗 + 审计留痕。
- 每片都遵守：只读、命名空间隔离、确认不降级、可回滚。

## 7. 明确不做的（YAGNI 边界）

- 不接 LangChain / LlamaIndex —— 会引入重量级依赖 + 与 trimum 的信任/能力模型冲突。
- 不做长文档 chunking 管线 —— 记忆是短结构，不需要。
- 不上 FAISS / 专用向量库 / 常驻向量服务 —— 库太小 + 单进程气质不符。
- 不用云 embedding API —— 与网络约束（校园网/直连）冲突。

## 一句话结论

trimum 的 RAG = **给现有记忆层（FTS5 关键词）补一条「本地 embedding + sqlite-vec」语义通道，再 RRF 混合排序**；
存储/命名空间/确认/审计全部复用现成的，**只加"语义召回"这一层**，且全程离线、只读、不破坏安全边界。
分三片 R1→R2→R3，R1 当天可拿正反馈。
