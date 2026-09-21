# LLM 模型路由、限流与回退

> 2026-09-21 定。**所有 LLM 调用点共用一处策略**：`src/trimum_core/llm_router.py`。
> 一句话：交我算 Qwen 当主力（免费，10 次/分硬限 → 客户端压到 9），DeepSeek 官方当兜底；
> 「跑代码/多步编排」的 agent 角色反过来——deepseek-flash 为主、Qwen 兜底。

## 1. 分工表：哪些活由谁干

| 角色 (`ROLE_*`) | 触发点（代码） | 频率 | 主模型 | 回退 | 为什么这么分工 |
|---|---|---|---|---|---|
| `policy` | `llm_policy._call_llm`：命令风险灰区裁决 | **最高**（每条可疑命令一次） | 交我算 `qwen3.8-27b` | DeepSeek `deepseek-flash` | 单命令进、固定 JSON 出、`max_tokens=200`、`temperature=0`，**还有 5 分钟决策缓存**；免费额度够，贵模型用在这里最亏 |
| `planner` | `planner_agent._call_llm_api_fallback`：自然语言 → Workflow | 中（每次任务分解一次） | `qwen3.8-27b` | `deepseek-flash` | 输出结构化 YAML/JSON，27B 够用；分解错了代价高 → 挂了立刻换强模型 |
| `transform` | `transform_agent._call_llm`：自然语言 → 命令/TARL | 中 | `qwen3.8-27b` | `deepseek-flash` | 短翻译（`max_tokens=1024`），翻不出来还有 TARL 兜底 |
| `experience` | `experience_learner._call_llm`：失败经验沉淀 | 低（失败事件触发） | `qwen3.8-27b` | `deepseek-flash` | 尽力而为，失败就当没学到 |
| `agent` | `agent_loop._chat_completion`：运行时会话 / 多步编排 / 流式 | 中高（多轮对话） | **`deepseek-flash`** | `qwen3.8-27b` | 要能力、要长上下文、要流式；这里花的是「体验」的钱，值得。反向回退保证 DeepSeek 挂了还能凑合用 |

> 换分工**不用改代码**：改 `.env` 里的 `AGENT_LLM_MODEL` 之类即可（见表 2）。

## 2. 实测模型清单（2026-09-21，别猜，看这

**交我算** `GET https://models.sjtu.edu.cn/api/v1/models`（`API_KEY`，校园网直连）
```
minimax, qwen, claw, deepseek-chat, deepseek-reasoner, minimax-m2.7, qwen3.8-27b
```
- 本项目用 **`qwen3.8-27b`**（实测可跑，见 §6 证据）；`qwen` 是同一档的别名。

**DeepSeek 官方** `GET https://api.deepseek.com/v1/models`（`DEEPSEEK_API_KEY`，走代理）
```
deepseek-flash, deepseek-v4-pro
```
- 回退模型用 **`deepseek-flash`**（官方两档里更便宜的一档，另一档是 `deepseek-v4-pro`）。
- ⚠️ **`deepseek-chat` 已经不在官方列表里** —— 项目里旧默认值写的就是它，本次一并改掉
  （`security_config.DEFAULT_SECURITY_YAML`）。历史配置里若还写着 `deepseek-chat`，
  会 4xx → 路由自动回退到 `deepseek-flash`，但那是白花一次配额。

## 3. env 键全表（都放 `.env`）

| 用途 | 键 | 默认（内置） |
|---|---|---|
| 主模型地址 | `TRIMUM_LLM_BASE_URL` | `https://models.sjtu.edu.cn/api/v1` |
| 主模型名 | `TRIMUM_LLM_MODEL` | `qwen3.8-27b` |
| 主模型 key（**间接引用**） | `TRIMUM_LLM_API_KEY_ENV` | 按基址推断：交我算 → `JIAOWOISAN_API_KEY`/`API_KEY`，DeepSeek → `DEEPSEEK_API_KEY` |
| 主模型 key（直接写值） | `TRIMUM_LLM_API_KEY` | 空（推荐用 `_ENV` 间接引用，同一把 key 不必写两遍） |
| 主模型速率上限 | `TRIMUM_LLM_RPM` | 交我算 **9**（硬限 10，留 1 次余量）；其他 provider **0 = 不限流** |
| 主模型超时/重试 | `TRIMUM_LLM_TIMEOUT` / `TRIMUM_LLM_MAX_RETRIES` | 30s / 1（1 = 只试一次就换 target） |
| 回退地址/模型/key | `TRIMUM_LLM_FALLBACK_{BASE_URL,MODEL,API_KEY_ENV}` | `https://api.deepseek.com/v1` / `deepseek-flash` / `DEEPSEEK_API_KEY` |
| 关掉回退 | `TRIMUM_LLM_FALLBACK_ENABLED=0` | 默认开 |
| **角色级覆盖** | `<ROLE>_LLM_{MODEL,BASE_URL,API_KEY,API_KEY_ENV,RPM,TIMEOUT,MAX_RETRIES}` | — |
| 角色级回退覆盖 | `<ROLE>_LLM_FALLBACK_{MODEL,BASE_URL,API_KEY_ENV,RPM}` | — |

`<ROLE>` ∈ `POLICY` / `PLANNER` / `TRANSFORM` / `EXPERIENCE` / `AGENT`（未登记的角色也支持：`<名字大写>_LLM_*`）。

**优先级**：角色级 env > 全局 env（`TRIMUM_LLM_*`）> 代码/yaml 里的默认值 > 内置默认。
一句话：**运维只改 .env 就能整体换模型，不用碰代码，也不用碰 `security.yaml`。**

**key 的解析顺序**（同一把 key 只写一次）：显式传入 > `<ROLE>_LLM_API_KEY` > `TRIMUM_LLM_API_KEY`
> `<ROLE>_LLM_API_KEY_ENV` / `TRIMUM_LLM_API_KEY_ENV` 指的变量 > yaml 的 `api_key_env` > 按基址推断。

**RPM 的一个坑（已修）**：`TRIMUM_LLM_RPM` 只在「这一级的地址也来自全局/默认」时继承。
角色自己把地址指到别家（如 `AGENT_LLM_BASE_URL=…deepseek.com`）时不会被交我算的 9 次/分绑住。

## 4. 限流怎么做的

- **令牌桶**（`llm_router.TokenBucket`）：按 provider（= base_url）一份配额，**预扣式**——
  `consume()` 先扣一次并返回「还要等几秒」，所以并发调用各排各的槽位，不会一起冲上去撞 429。
- 交我算硬配额是 **10 次/分、300k tokens/分、1B tokens/周**，客户端按 **9 次/分**（≈每 6.7s 一次）放行。
- DeepSeek 官方没有硬 RPM → 默认不限流（也省得把体验拖慢）。
- **已知边界**：桶是**进程内**的。daemon 与 CLI 各自持有 9 次/分的预算，
  两者同时跑时瞬时合计可能超过 10 次/分。跨进程限流（文件锁 + 共享状态）见 §8 待办。

## 5. 失败与回退

**失败分类**（`llm_router.should_switch` / `is_retryable`）

| 情况 | 处理 | 该 provider 冷却 |
|---|---|---|
| HTTP 429（限流） | 不原地重试，**直接换下一个 target** | 60s |
| 5xx | 先按 `MAX_RETRIES` 重试（退避 0.5s/1s），再换 | 30s |
| 400/401/403/404（key 或模型名不对） | 直接换 | 120s |
| 连不上/超时 | 直接换 | 15s |
| 解析失败（JSON 烂了 / choices 空） | 算这个 target 失败、可重试，但**不冷却**（provider 没毛病） | — |

**冷却**是按 provider 记的、跨角色共享（429 是账号级配额，本该共享）。
冷却期内该 provider 直接跳过，全都在冷却 → 抛 `LlmCallError`（不会傻等）。

**全不可用时的降级路径**（各调用点自己的老逻辑，一个都没丢）

| 角色 | 降级行为 |
|---|---|
| `policy` | 回正则结论，`reason` 带 `[llm-fallback]` |
| `transform` | 回 TARL 兜底（`confidence 0.1`） |
| `planner` | 返回 `None` → 上层报「无法生成计划」 |
| `experience` | 返回 `None` → 这条失败不沉淀 |
| `agent` | 返回空内容 → 调用点走正则计划 |

## 6. 代码落点

```
src/trimum_core/llm_router.py     路由 + 限流 + 回退（唯一策略处，不碰 HTTP）
src/trimum_core/env_file.py       .env 加载器（TRIMUM_ENV_FILE → $TRIMUM_HOME/.env → ~/.trimum/.env → ./.env，按 key 叠加、已有环境变量优先）
scripts/llm_env_dropin.sh         真机：给 trmd 加 EnvironmentFile（--check/--apply/--smoke/--rollback）
tests/test_llm_router.py          27 项（选谁/等多久/失败换谁，含异步）
tests/test_env_file.py            6 项
tests/conftest.py                 两个隔离 fixture：reset_llm_router_state（牌桶 + 冷却）、isolate_process_env（用例前后快照/还原 os.environ）
```

`llm_router` 对外只有 6 个函数：`resolve_targets` / `run_with_fallback` / `arun_with_fallback`
/ `resolve_env_api_key` / `stats` / `reset_state`。**HTTP 由调用点在 `attempt(target)` 里自己发**
（urllib / httpx / 流式都行），所以既有测试继续能用 `@patch("urllib.request.urlopen")` 打桩。

5 个调用点各自传进来的 yaml/构造参数只当**默认值**（env 可以整体覆盖）：

| 调用点 | attempt 用的传输 | 传进来的默认值来源 |
|---|---|---|
| `llm_policy._call_llm` | `httpx.AsyncClient` | `~/.trimum/security.yaml` 的 `llm:` 段（含 `fallback:` 子段） |
| `planner_agent._call_llm_api_fallback` | `urllib` | 构造参数（`PLANNER_LLM_*` 已在构造时读入） |
| `transform_agent._call_llm` | `urllib` | 构造参数（`TRANSFORM_LLM_*`） |
| `experience_learner._call_llm` | `urllib`（`asyncio.to_thread`） | 构造参数（`EXPERIENCE_LLM_*`） |
| `agent_loop._chat_completion` | `httpx.AsyncClient`（含 SSE 流式） | `security.yaml` 的 `llm:` 段 |

> 顺带修掉两个老 bug：`planner_agent` 里 `TrimumError`/`TRMErrorCode` **从没被 import**
> （那几条分支一跑到就 NameError）；`agent_loop._chat_completion` 之前只看
> `DEEPSEEK_API_KEY`，现在 key 由路由决定（`.env` 写什么就用什么）。

## 7. 真机运维（Ubuntu 100.115.86.48）

**为什么需要 drop-in**：`trmd.service` 本身没有 `EnvironmentFile`，daemon 环境里只有
`PATH` 与 `TRIMUM_SOCKET` —— 所以「.env 里明明配了 key，`trm doctor` 还是 MISSING」。
现在多了一个 drop-in `/etc/systemd/system/trmd.service.d/30-llm-env.conf`：

```ini
[Service]
EnvironmentFile=-/opt/trimum/.env      # 前导 - = 文件不在也不报错
```

两份 .env（同一批键，各归其主）：

| 谁用 | 文件 | 属主/权限 | 怎么被读到 |
|---|---|---|---|
| daemon（trmd） | `/opt/trimum/.env` | `root:guzhujushi 0600` | systemd `EnvironmentFile`（systemd 以 root 读，再降权跑） |
| CLI（`trm`，用户 guzhujushi 跑） | `~/.trimum/.env` | `guzhujushi 0600` | `trimum_core.env_file`（CLI/daemon/client 入口都会 `ensure_loaded()`） |

**常用命令**

```bash
# 看现状 + 看路由表（不动任何东西，非 root 也能跑）
bash /tmp/llm_env_dropin.sh --check

# 应用 / 冒烟 / 回滚（都要 sudo）
sudo bash /tmp/llm_env_dropin.sh --apply
sudo bash /tmp/llm_env_dropin.sh --smoke     # 真调一次主模型（花一次配额）
sudo bash /tmp/llm_env_dropin.sh --rollback  # 删 drop-in → daemon 不再读 .env
```

**改模型/换分工**：改 `/opt/trimum/.env`（daemon）与 `~/.trimum/.env`（CLI）→ `systemctl restart trmd`。
改完务必 `--check` 看一眼路由表，或直接 `--smoke`。

**本轮实测证据（2026-09-21 22:41）**

```
== 当前 LLM 路由（部署树的真实解析结果）
policy     primary  model=qwen3.8-27b      rpm=9   key_env=JIAOWOISAN_API_KEY   key=有
policy     fallback model=deepseek-flash   rpm=0   key_env=DEEPSEEK_API_KEY     key=有
planner/transform/experience  同上
agent      primary  model=deepseek-flash   rpm=0   key_env=DEEPSEEK_API_KEY     key=有
agent      fallback model=qwen3.8-27b      rpm=9   key_env=JIAOWOISAN_API_KEY   key=有

== 网络冒烟
OK  走的 target：primary:qwen3.8-27b@models.sjtu.edu.cn  回复：可用
== 验证：daemon 环境里有 TRIMUM_LLM_* / JIAOWOISAN_API_KEY / DEEPSEEK_API_KEY（只看键名）
== trm doctor：LLM API connectivity: https://models.sjtu.edu.cn/api/v1（OK）；env DEEPSEEK_API_KEY / JIAOWOISAN_API_KEY / API_KEY 全 OK
```

## 8. 待办与已知坑

- [ ] **跨进程限流**：令牌桶在进程内，daemon 与 CLI 各 9 次/分。要做的话：文件锁 +
      共享状态（`~/.trimum/llm-throttle.json`），把 `TokenBucket` 换成 `FileTokenBucket` 即可（接口已收口）。
- [ ] **token 计量**：交我算还有 300k tokens/分、1B tokens/周 两个维度，现在只限了「次数」。
      可在 `attempt` 返回值里带 usage，累计到 `stats()`（`agent_loop` 已有 `TokenUsage`）。
- [ ] **429 的 `Retry-After`**：现在按状态码给固定 60s，没读响应头。
- [ ] **`trm doctor` 显示路由**：doctor 只显示「env 有没有」，不显示「每个角色实际用谁」；
      路由表目前靠 `llm_env_dropin.sh --check`。可以把路由塞进 `trm doctor --json`。
- [ ] **成本账本**：agent 角色走的是收费的 deepseek-flash，值得按天记一笔调用次数/花费。
- 坑：`~/.trimum/.env` 里若有历史遗留键（本机就有一份只含 `OPENAI_*` 的），
      加载器是**按 key 叠加**的，不会把仓库根 `.env` 整个挡掉（这个 bug 已修 + 有回归测试）。
- 坑（已修，2026-09-21）：`ensure_loaded()` 是**进程级只跑一次** + 会把 `.env` 写进 `os.environ` ⇒
      **用例之间会互相污染**（先跑过 `cli.main()` 的用例，会把开发机 `.env` 漏给后面所有用例，
      实测让 `test_transform_agent` 的 base_url 被顶掉、`test_env_list_sorted` 首行变成 `163_EMAIL=`）。
      现由 `tests/conftest.py::isolate_process_env` 按用例快照/还原 `os.environ` 兜住；
      **新增会读 env 的用例，请自己挡 `.env`**（`monkeypatch.setattr(env_file, "candidate_paths", ...)`，
      见 `test_cli_commands::test_health_json_includes_api_key_presence`）。
