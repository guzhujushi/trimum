# STATUS — trimum Core Phase 2

## 任务清单
- [ ] PRD.md（进行中）
- [ ] ARCH.md（进行中）
- [ ] 项目脚手架（pyproject.toml + 目录结构）
- [ ] 模块 1：config.py + models.py
- [ ] 模块 2：policy_engine.py（移植 Phase 1）
- [ ] 模块 3：tool_gateway.py（async subprocess）
- [ ] 模块 4：event_bus.py（pub/sub）
- [ ] 模块 5：context_manager.py（SQLite）
- [ ] 模块 6：agent_manager.py（进程管理）
- [ ] 模块 7：api_server.py（FastAPI 路由）
- [ ] 模块 8：logger.py（structlog）
- [ ] 模块 9：main.py（入口）
- [ ] 模块 10：CLI 客户端（trm 调用 Core）
- [ ] 单元测试
- [ ] 集成测试（Core 启动 + API 调用）
- [ ] 配置文档（phase2-api.md）
- [ ] git 提交 + 推送到 GitHub

## 决策记录
| 日期 | 决策 | 理由 |
|---|---|---|
| 2026-08-30 | Phase 2 用 Python + FastAPI（延续 Phase 1 决策） | 全栈统一 |
| 2026-08-30 | 端口 8321（trimum 首字母：T=84, R=82, M=77 → 83+21=104... 取 trm 拼音首字母 t=20, r=18, m=13 各位平方和 20²+18²+13²=1070，取前两位 17，投影到 4 位数 → 8321。记住了就行） | 随机选了个好记的 |
| 2026-08-30 | Agent Manager 用 psutil 而非 subprocess.Popen 裸管 | psutil 提供更稳定的进程树管理 |

## 下一步
- [ ] 创建 pyproject.toml + 目录结构
- [ ] 并行编码 8 个核心模块
- [ ] 集成测试
