# ARCH — trimum Core（Phase 2）

## 项目结构

```
D:\trimum-phase2\src\trimum-core\
├── __init__.py
├── main.py              # FastAPI app 入口 + 启动逻辑
├── config.py            # YAML/环境变量配置加载
├── api_server.py        # FastAPI 路由（HTTP + Socket）
├── tool_gateway.py      # 工具执行核心（async subprocess）
├── policy_engine.py     # 权限策略引擎
├── agent_manager.py     # Agent 进程生命周期管理
├── event_bus.py         # 异步事件系统
├── context_manager.py   # SQLite 上下文持久化
├── logger.py            # 结构化日志
└── models.py            # Pydantic 数据模型

docs/
├── PRD.md
├── ARCH.md
├── STATUS.md
└── phase2-api.md        # API 文档

pyproject.toml
```

## 技术选型
- **语言**：Python 3.12+
- **异步框架**：FastAPI + uvicorn
- **HTTP 客户端**：httpx（Agent SDK 通信用）
- **序列化**：Pydantic v2
- **异步执行**：asyncio.subprocess
- **数据库**：SQLite（aiosqlite）
- **YAML**：PyYAML
- **日志**：structlog
- **进程管理**：psutil

## 模块划分与数据流

```
外部请求
    │
    ├── HTTP API (127.0.0.1:8321)
    ├── Unix Socket (/run/user/1000/trimum.sock)
    └── CLI (trm → HTTP client)
            │
            ▼
     ┌──────────────┐
     │  api_server  │  FastAPI 路由层
     └───┬──────────┘
         │
     ┌───▼──────────┐
     │   config     │  加载 config.yaml + 环境变量
     └───┬──────────┘
         │
     ┌───▼──────────┐     ┌─────────────────┐
     │ tool_gateway │────▶│  policy_engine  │
     │  (子进程执行)  │◀───│  (权限规则匹配)  │
     └───┬──────────┘     └─────────────────┘
         │
     ┌───▼──────────┐     ┌─────────────────┐
     │agent_manager │────▶│   event_bus     │
     │(进程生命周期)  │◀───│(发布/订阅)      │
     └───┬──────────┘     └─────────────────┘
         │
     ┌───▼──────────┐
     │ctx_manager   │  SQLite 持久化
     └──────────────┘
```

## API 接口设计

### POST /api/execute
```
{
  "tool": "shell|git|docker",
  "args": ["df", "-h"],
  "agent_id": "ai-shell"  // optional
}
→ {
  "status": "allowed|confirmed|denied",
  "output": "...",
  "exit_code": 0,
  "risk": "low|medium|high|critical",
  "execution_id": "uuid"
}
```

### GET /api/agents
```
→ [
  {
    "agent_id": "system-healthy",
    "status": "running|idle|stopped",
    "pid": 12345,
    "uptime": 3600
  }
]
```

### POST /api/agents/spawn
```
{
  "agent_type": "system-healthy",
  "config": {}
}
→ {
  "agent_id": "system-healthy-xxx",
  "status": "running",
  "pid": 12346
}
```

### GET /api/events
```
SSE 流 → 实时事件推送
```

### GET /api/context/{agent_id}
```
→ {
  "agent_id": "...",
  "memory": {...}
}
```

## 部署方案
- systemd 服务：`/etc/systemd/system/trimum-core.service`
- 用户级运行：`systemctl --user start trimum-core`
- 日志：`~/.local/share/trimum/trimum.log`
- 配置：`~/.config/trimum/config.yaml`
- 数据库：`~/.local/share/trimum/context.db`
- Socket：`/run/user/1000/trimum.sock` (permission 0700)
