# Codex 侧模型分工与「限流降级」调研（2026-09-21）

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
| `codex exec -p qwen` 端到端通 | `model: qwen3.8-27b` / `provider: sjtu-jiaowoisan` / 回复「可以」/ 退出码 **0** |
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
- 该 `.ps1` 存成 **UTF-8 with BOM**：Windows PowerShell 5.1 用 `-File` 跑「无 BOM 的 UTF-8」会按 GBK 解，
  中文直接把脚本解析弄挂（已实测）。仓库里 bash 脚本「UTF-8 无 BOM」的规矩是给 Linux shell 的。
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

## 6. 本次变更记录

- 新增 `~/.codex/qwen.config.toml`、`~/.codex/ds.config.toml`（`config.toml` 改过一次又回滚：
  按 0.151 的要求挪成独立文件；备份在 `~/.codex/backups/config.toml.20260921-230249.bak`）。
- 新增 `scripts/codex-model.ps1`（本仓库）。
- 真机证据：`POST /api/v1/responses` 200 + `codex exec -p qwen` 回复「可以」（两次，退出码 0）。
