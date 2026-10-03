# Codex 侧模型分工与「限流降级」调研（2026-09-21 立；2026-09-22 复盘修订）

> 需求：简单任务用交我算的 Qwen（免费），困难任务用 deepseek-flash；
> 并希望「像 trimum 一样限流后自动降级到 deepseek-flash」。

## 0. 一句话结论

- **Codex 自身做不到「限流后自动降级到另一个 provider」** —— 它没有任何这类配置键，
  只在限流时**提示**你换模型（Notice 里的 `hide_rate_limit_model_nudge` 是关掉这个提示的开关）。
- **能立刻用的是任务级 profile 切换**：本机已建好 `qwen` / `ds` 两个 profile，`codex -p qwen` 或
  `scripts/codex-model.ps1 qwen` 即可（§3）。
- 想真做到「限流后降级」，只能**在 Codex 前面加一层本地路由代理**（§4，待裁决是否动手）。
  好消息：双方都原生说 Responses API，代理**不需要协议翻译**，正好复用 `trimum_core.llm_router`。

## 1. 实测事实（都有证据，别猜）

| 事实 | 证据 |
|---|---|
| Codex `0.151.0-alpha.7.2` 的 `wire_api` **只接受 `responses`** | 故意写 `wire_api = "bogus"` → `unknown variant \`bogus\`, expected \`responses\`` |
| 交我算 `POST /api/v1/responses` **可用**（不用写 shim 翻译层） | 最小请求 **HTTP 200**：`object:"response"`、`model:"qwen3.8-27b"`、回复 `Pong!...`、24 tokens；响应里有 `_litellm_tpm_reserved_model` ⇒ 后端是 **LiteLLM 网关** |
| `codex exec -p qwen` 端到端通 | `model: qwen3.8-27b` / `provider: sjtu-jiaowusuan` / 回复「可以」/ 退出码 **0**（0.151.0-alpha.7.2；**0.152.0 于 2026-09-22 复验仍通**） |
| profile **不能**写在 `config.toml` 里 | 写了 `[profiles.qwen]` → `--profile \`qwen\` cannot be used while ... contains legacy [profiles.qwen] config; move those settings into ...\qwen.config.toml` |
| Codex **没有** provider 级 fallback 配置 | 全二进制扫 `*fallback*` 标识符，只有这些：`disable_in_process_fallback`（CodeModeHost）、`auto_compact_fallback_*`（TokenBudget）、`allow_provider_model_fallback`（models-manager 内部：模型不在 provider 模型表里时回落）、session 事件 `requested_model`/`fallback_model`（请求的模型不可用时回落）。**没有**「429 → 换 provider」 |
| 429 现状只是重试 | `model_providers.<id>.request_max_retries` / `stream_max_retries`（同 provider 退避重试，不换家） |
| 会话中途换模型的能力在开发中 | feature flag `step_model_switching`（`under development`，默认 false；`core/src/session/step_settings.rs`） |
| 未登记的模型会有警告 | `Model metadata for \`qwen3.8-27b\` not found. Defaulting to fallback metadata; this can degrade performance and cause issues.` |

## 2. 关键约束：10 次/分 vs 每次调用 ~15k tokens

实测一次 `codex exec`（2 个字的回复）：

```
tokens used  15,211     # 第一次；后来 14,084
```

- **次数**：交我算是 10 次/分 —— 一个正常 Codex turn（工具循环十来次调用）**几秒就打满**；
- **token**：15k × 10 = 150k/分 < 300k/分，token 维度不是瓶颈；周额度 1B ≈ 6~7 万次调用，也够；
- ⇒ **Qwen 适合「单次小任务」**（`codex-model.ps1 qwen -Exec "..."`，一件事、一把梭），
  长会话 / 多步问题仍用 `ds`。指望「全部靠 Qwen 免费跑」会一直撞 429。

## 3. 现在怎么用（已落地）

- profile 文件（Codex 0.151 必须是独立文件）：`~/.codex/qwen.config.toml`、`~/.codex/ds.config.toml`；
  原来的 `~/.codex/sjtu-min.config.toml` 是同类先例。
- 直接命令：`codex -p qwen` / `codex -p ds`；脚本化：`codex exec -p qwen --skip-git-repo-check -s read-only "..."`。
- 便捷入口：`scripts/codex-model.ps1`（顺带把 trimum 的 `.env` 灌进本次进程的环境 ——
  `DEEPSEEK_API_KEY` / `JIAOWOISAN_API_KEY` **都不是持久化的用户环境变量**，Codex 又只认环境变量取 key）：
  ```powershell
  .\scripts\codex-model.ps1 qwen                                  # 交互式，Qwen
  .\scripts\codex-model.ps1 ds                                    # 交互式，deepseek-flash
  .\scripts\codex-model.ps1 qwen -Exec "把 TODO.md 的提交号回填"   # 非交互一把梭
  ```
- **免记参数的入口**（2026-09-22 加；给「不想敲脚本路径」的场景）：
  `scripts\codex-qwen.cmd`（交我算 Qwen）/ `scripts\codex-ds.cmd`（deepseek-flash）。
  纯 ASCII 批处理，内部转发到 `powershell -NoProfile -ExecutionPolicy Bypass -File ...\codex-model.ps1 <profile>`：
  **绕开执行策略**、双击也能跑；`-NoProfile` 下 `codex` 仍能从 PATH 找到（已实测，交互式与 `-Exec` 两种都通）。- 该 `.ps1` 存成 **UTF-8 with BOM**：Windows PowerShell 5.1 用 `-File` 跑「无 BOM 的 UTF-8」会按 GBK 解，
  中文直接把脚本解析弄挂（已实测）。仓库里 bash 脚本「UTF-8 无 BOM」的规矩是给 Linux shell 的。
  ⚠ **任何脚本/工具改写这个文件时必须保留 BOM**（2026-09-22 踩过：用
  `[System.IO.File]::WriteAllText($p, $t, (New-Object System.Text.UTF8Encoding($true)))` 才是带 BOM 的 UTF-8；
  写成 `$false` 会把 BOM 洗掉，PS 5.1 立刻按 GBK 解、脚本语法崩成一堆 `Unexpected token`）。
- 可选（消掉「模型元数据缺失」警告）：profile 里加 `model_context_window` / `model_auto_compact_token_limit`
  （键名来自二进制里的 settings 结构）。**别拍脑袋填数**，先跟交我算确认 qwen3.8-27b 的实际窗口。
- 任务级分工表（哪条任务用哪个模型）：见 `TODO.md` 的「🤖 Codex 模型分工」一节，条目上带 `【Qwen】` / `【DS】` 标签。

## 4. 要真「限流后降级」：本地路由代理（待裁决）

Codex 只认 `responses`，而**交我算与 DeepSeek 双方都原生说 `responses`** ⇒ 代理不需要协议翻译，
就是「按策略挑目标重发 + 令牌桶 + 429/失败换目标」的**直通转发** —— 正是 `trimum_core.llm_router`
已经有的能力（`resolve_targets` / `TokenBucket` / 失败分类 + 冷却）。

| 方案 | 做法 | 优点 | 代价 |
|---|---|---|---|
| **B1 LiteLLM proxy** | `pip install 'litellm[proxy]'` + 一份 YAML（`rpm` + `router_settings.fallbacks`） | 现成、成熟、文档多 | 新装 ~100MB 依赖 + 常驻服务 |
| **B2 trimum 原生 `trm codex-proxy`**（推荐） | 一个 FastAPI 直通转发 `/v1/responses`：primary = 交我算 Qwen（9 次/分令牌桶）→ 429/超时/5xx → deepseek-flash；复用 `llm_router` 的策略与冷却 | **不新增依赖**（fastapi/httpx 已在）；与 daemon 共用同一套键与口径；顺手能把 trimum 既有的「跨进程限流」待办做掉 | 要写 ~200 行 + 测试 |

B2 落地后 Codex 侧接线（记住 `env_key` 必须有值，本地回环随便给个非空串）：

```toml
[model_providers.trm-router]
name = "trm-router"
wire_api = "responses"
base_url = "http://127.0.0.1:57323/v1"
env_key = "TRIMUM_ROUTER_TOKEN"
```

**期望值要摆正**：这条路的真实价值是「免费的额度能蹭就蹭，蹭不到**不中断**」，
而不是「整体变免费」—— 一旦限流，长会话会大量落到收费的 deepseek-flash。

## 5. 待决策

- [ ] B1 / B2 / 都不做（只用手动 profile 切换）
- [ ] 若做 B2：默认端口、是否随 `trmd` 同生命周期（systemd user unit）、降级比例要不要记账
- [ ] `qwen` profile 是否补 `model_context_window`（要先确认交我算的实际窗口）
- [ ] 环境变量 `JIAOWOISAN_API_KEY` 是否随 provider 一起改名（`JIAOWOSUAN_API_KEY`）？
      它会牵动 `src/`（`llm_router.py` / `doctor.py` / `health.py` / `security_config.py`）、`tests/`、
      `scripts/llm_env_dropin.sh` 与真机 drop-in —— 建议**只加新名、保留旧名作别名**，别让真机 daemon 起不来。

## 6. 本次变更记录

- 新增 `~/.codex/qwen.config.toml`、`~/.codex/ds.config.toml`（`config.toml` 改过一次又回滚：
  按 0.151 的要求挪成独立文件；备份在 `~/.codex/backups/config.toml.20260921-230249.bak`）。
- 新增 `scripts/codex-model.ps1`（本仓库）。
- 真机证据：`POST /api/v1/responses` 200 + `codex exec -p qwen` 回复「可以」（两次，退出码 0）。

## 7. 2026-09-22 复盘：为什么「qwen3.8-27b / sjtu-jiaowoisan 都不行」

**一句话**：`/model` 只改**模型名**、**不改 provider**；而 `sjtu-jiaowusuan` 是 **provider 名、不是模型名**。
会话的 provider 一直是 `deepseek-api`，所以请求全打到 DeepSeek，被回
`The supported API model names are deepseek-flash, deepseek-v4-pro, but you passed <你填的那个>`。
**换 provider 只能重开进程**：`codex -p qwen` / `.\scripts\codex-model.ps1 qwen`。
**怎么起（三条任选，都已实测）**：

| 场景 | 命令 |
|---|---|
| 双击 / 不想敲路径 | `D:\trimum\scripts\codex-qwen.cmd`（或 `codex-ds.cmd`） |
| 交互式 | `.\scripts\codex-model.ps1 qwen` |
| 一次性 | `.\scripts\codex-model.ps1 qwen -Exec "把 TODO.md 的提交号回填"` |

起来后 TUI 顶部写 `model: qwen3.8-27b`、底部写 `qwen3.8-27b default · D:\trimum` —— 看到这两处就对了。
（**TUI 横幅不显示 provider**，「现在是不是走交我算」要靠**是从哪个入口起的**来判断。）

| 你填进 `/model` 的 | 实际发给了谁 | 结果 |
|---|---|---|
| `qwen3.6-27b` | `deepseek-api` | `invalid_request_error` —— DeepSeek 不认这个模型名 |
| `qwen3.8-27b` | `deepseek-api` | 同上 —— 这个模型只存在于 provider `sjtu-jiaowusuan` 上 |
| `sjtu-jiaowoisan`（或改好名的 `sjtu-jiaowusuan`） | `deepseek-api` | 同上 —— 它是 provider 名，永远不该进 `/model` |

证据：09-22 的 6 条 rollout，`session_meta.model_provider` 全是 `deepseek-api`，
`turn_context.model` 分别是上面三个值，紧跟一条来自 DeepSeek 的 `invalid_request_error`。

**同时修掉 `scripts/codex-model.ps1` 的两个真 bug**（本机实测复现，不是猜的）：

| bug | 现象 | 修法 |
|---|---|---|
| 选错 `.env` | 候选表把 `~/.trimum/.env`（只剩 `OPENAI_*` 的老 stub）排在仓库 `.env` **之前**，旧实现**只取第一个存在的候选** ⇒（父进程环境里也没有时） `JIAOWOISAN_API_KEY` / `DEEPSEEK_API_KEY` 一个都没注入，`codex -p qwen` 只报 `Missing environment variable: JIAOWOISAN_API_KEY.` | 低→高优先级依次加载（仓库根 `.env` 权威）+ 进程原有变量优先；起 codex **之前**校验 profile → provider → `env_key`，缺了给人话报错 |
| PS 5.1 把 codex 的 stderr 当致命错误 | 原生程序写 stderr 的每行被包成 ErrorRecord，配上 `$ErrorActionPreference = 'Stop'` ⇒ codex 一启动（总会写 `Reading additional input from stdin...`）就抛错中止，**`-Exec` 路径一次都没真正跑成** | 在 `& $codex` 前把偏好放回 `Continue`，成败看 `$LASTEXITCODE` |

**署名改正**：provider `sjtu-jiaowoisan` → **`sjtu-jiaowusuan`**（2026-09-22 定名：先误改为 `jiaowosuan`，经确认最终用 `jiaowusuan`）。
环境变量 `JIAOWOISAN_API_KEY` **本轮未动**（见 §5 待决策）。

**复验**：2026-09-22 07:33 / `codex-cli 0.152.0`（昨天的证据取自 0.151.0-alpha.7.2，本机已升级，故重验）。
先清空进程里的 key，再跑 `.\scripts\codex-model.ps1 qwen -Exec "只回复两个字：可以"` →
`provider: sjtu-jiaowusuan` / 回复「可以」/ 退出码 **0**。
