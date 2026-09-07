# 三重记忆体系

> 最后更新：2026-09-01
> 三权分立：Agent 私有记忆 / 项目共享上下文 / Planner 全局上下文

---

## 架构

```
┌─────────────────────────────────────────────┐
│                ContextManager                 │
│               SQLite + FTS5                  │
│                                              │
│  ┌─────────────┐  ┌──────────┐  ┌─────────┐ │
│  │ Agent 私有   │  │ 项目共享  │  │ 全局     │ │
│  │ agent_memory│  │project_ctx│  │global_ctx│ │
│  ├─────────────┤  ├──────────┤  ├─────────┤ │
│  │ 自己读:不需  │  │读:需通知 │  │Planner  │ │
│  │ 确认        │  │写:无需   │  │长期记忆  │ │
│  │ 跨 Agent:   │  │ 确认     │  │         │ │
│  │ 需 Security  │  │         │  │         │ │
│  └─────────────┘  └──────────┘  └─────────┘ │
└─────────────────────────────────────────────┘
```

## 分类

| 层级 | Namespace | 存储位置 | 谁读写 | 确认策略 |
|---|---|---|---|---|
| **Agent 私有** | `agent_memory` | `~/.trimum/memory/agents/<agent_name>.db` | 所属 Agent 读写，跨 Agent 需 Security 确认 | 自己读不确认，别人读需确认 |
| **项目共享** | `project_ctx` | `~/.trimum/memory/projects/<project_id>.db` | Workflow 内 Agent 共享 | 读需弹窗确认，写不确认 |
| **全局** | `global_ctx` | `~/.trimum/memory/global.db` | Planner Agent / 系统级 | 读需确认 |

## FTS5 全文搜索

全部三层记忆共用同一 FTS5 索引（`context_fts`），支持标准查询语法：

```sql
-- 基本搜索
MATCH 'key_word'

-- 字段限定
MATCH 'namespace:"agent_memory" AND (memory OR context)'

-- 短语
MATCH '"project_name" AND key:version'
```

### 搜索接口

```python
# 全局搜索
results = await cm.search("blog deployment script")

# 按命名空间搜索
agent_memories = await cm.search_by_namespace("RAM threshold", "agent_memory")

# 带限制
results = await cm.search("nginx config", limit=5)
```

### 自动同步

FTS5 索引自动跟随 CRUD 操作：
- `set()` → 自动 INSERT OR REPLACE 到 FTS
- `delete()` → 自动从 FTS 删除
- `clear_agent()` → 批量 FTS 清理

## 文件存储结构

```
~/.trimum/memory/
├── agents/
│   ├── transform_agent.db
│   ├── planner_agent.db
│   └── ...
├── projects/
│   ├── trimum.db
│   ├── myblog.db
│   └── ...
├── global.db                  # 全局上下文
└── context_fts.db             # FTS5 索引（可共用）
```
