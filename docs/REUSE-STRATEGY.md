# 开源项目复用策略 — Phase 2 实况版

> 更新于 2026-08-31，反映 Phase 2 实际落地情况。

## 自研 vs 复用的实际占比（Phase 2）

```
Phase 2 Core  ██████████████░░░░  75% 自研 + 25% 复用（psutil/structlog/Pydantic）
```

Phase 2 结束后，大部分核心逻辑（Agent Registry、Router、Planner、Workflow Engine、Tool Gateway、Policy Engine、Event Bus）均为**自研**。复用的是基础设施级库（psutil、structlog、Pydantic、FastAPI、aiosqlite）。

其他 Phase 的复用策略不变（见下方原文），等 Phase 3+ 实施时再更新。

---

以下是 v1.1 原始复用策略，待 Phase 3 启动时重新验证：

> [原始计划内容——参考 git history 的 REUSE-STRATEGY.md v1.1]
