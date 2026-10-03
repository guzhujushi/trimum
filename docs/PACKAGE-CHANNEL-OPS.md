# 官方分发包渠道 —— 运维手册（E5）

> 来源：E5 第三片步骤 2（2026-09-21）。信任模型见 `docs/ECOSYSTEM-STRATEGY.md` §7（内置根 / 校验链 /
> 安装 ≠ 授权）、包格式 §7.4、安装与卸载口径 §7.5 / §7.6；模块与红线见 `docs/ARCH.md`
> 「官方分发渠道（E5）」。
>
> 状态：**发布方闭环与使用者闭环都已在本地跑通，不依赖官网、不依赖 TLS**。
> `DEFAULT_INDEX_URL = https://trimum.dev/packages/index.json5` 仍是占位 —— 站点上线前用
> `--index` 或 `TRIMUM_PKG_INDEX` 指到真实目录即可（`trm install` 全程只信包内签名与内置根）。

---

## 0. 一条链，谁做什么

| 角色 | 命令 | 干什么 |
|---|---|---|
| 发布方（一次） | `trm pkg root-init` | 造根：公钥进仓库，私钥只在本机 |
| 发布方（按需） | `trm pkg signer-init --name N` | 由根签发签名者证书；**能力清单写在这里** |
| 发布方（每个包） | `trm pkg create <dir> -o x.trmpkg …` | 打包并签名 |
| 发布方（每次发布） | `trm pkg index dist/ -o dist/index.json5 …` | 扫目录 → 签名索引 → 落盘 |
| 发布方（上线） | 复制 `dist/` 整个目录 | 索引与包放同一目录，`url` 是相对路径 |
| 使用者 | `trm install <name>` / `--file` / `--list` | 取官方目录或本地包，校验后落地并登记 |
| 使用者 | `trm install --remove <name> --yes` | 卸载：删登记过的目录 + 划掉登记行 |

`<TRIMUM_HOME>` 默认 `~/.trimum`（Windows：`%USERPROFILE%\.trimum`），可用环境变量 `TRIMUM_HOME` 覆盖；
内置根的位置可用 `TRIMUM_TRUST_ROOT` 覆盖（测试与内网自建根都靠它）。

---

## 1. 造根（整个渠道只做一次）

```bash
trm pkg root-init                      # 默认写 <TRIMUM_HOME>/trust/
```

产出两份文件，去向完全不同：

| 文件 | 去哪 | 说明 |
|---|---|---|
| `trimum-root.crt` | **提交进仓库**（`config/trust/trimum-root.crt`） | 内置根＝所有人的信任锚，公钥 |
| `trimum-root.key` | **只留发布方本机**（权限 0600） | 丢了 = 只能换根；泄露 = 谁都能签官方包 |

**红线**：`root-init` / `signer-init` 拒绝把私钥写进 git 工作树（`--out ./config/trust` 这种手滑直接报错），
只有显式 `--insecure-key-output` 才放行；`.gitignore` 的 `*.key` / `*.pem` 是第二道保险。
换根后要把新指纹同步进 `config/trust/README.md`。

## 2. 建签名者（能力清单的载体）

```bash
trm pkg signer-init --name trimum-release --tools shell,fs --max-risk medium
```

落在 `<TRIMUM_HOME>/trust/signers/trimum-release.crt` + `.key`。
证书里的 `capabilities`（`tools` / `max_risk` / `expires_at` / `scope`）**不是文档，是运行期输入**：
`capability.py` 会把它与用户身份证书、包登记取交集，**只收紧、不放宽**（网关 Layer 2.6）。
所以「换能力」= 换签名者（要改能力就重新签一份证书，而不是改配置文件）。

## 3. 打包

```bash
trm pkg create ./agents/demo -o dist/demo-1.0.0.trmpkg \
  --name demo --type agent --version 1.0.0 --entry main.py \
  --requires python --requires git \
  --signer-cert "$TRIMUM_HOME/trust/signers/trimum-release.crt" \
  --key "$TRIMUM_HOME/trust/signers/trimum-release.key"
```

- `--type` 决定落地目录：`agent` → `agents/`、`tool` → `tools/`、`workflow` → `workflows/`、`skill` → `skills/`。
- **拒绝无签打包**：没有 `--signer-cert` + `--key` 直接报错；签名者证书必须**由该根签发**，否则拒。
- `--requires` 是外部依赖（按 PATH 探测），**安装时缺依赖只警告不拒装**（装好了但现在还用不了 ≠ 包有问题）。
- 建议按 `<name>-<version>.trmpkg` 命名：索引的 `url` 取的就是它，便于人工核对。

## 4. 建索引（发布方闭环的最后一步）

```bash
trm pkg index dist/ -o dist/index.json5 \
  --signer-cert "$TRIMUM_HOME/trust/signers/trimum-release.crt" \
  --key "$TRIMUM_HOME/trust/signers/trimum-release.key"
```

索引回答「**去哪拿这个包**」，所以它本身也必须签名 —— 不签名的索引等于把「用哪个包」交给中间人。
`trm pkg index` 的四条口径：

1. **只收录验得过的包**：`dist/` 里任何一个 `.trmpkg` 验不过（被改过 / 不是这个根签的），整个动作失败并
   逐条列出原因，**不写索引** —— 「悄悄少一个包」比「报错」危险得多。
2. **字段取自校验过的 manifest**，不是文件名：文件叫 `whatever.trmpkg` 也没关系，条目里的 `name` /
   `type` / `version` / `entry` / `requires` 一律以包内 manifest 为准。
3. **`url` 相对索引位置**（`/` 分隔，支持子目录）：索引与包放进同一目录树就能离线安装。
4. **写完自检**：刚签出来的索引会立刻就地验一遍（签名 + 证书链），验不过就报错 —— 否则「签名」只是自我安慰。

**一改包就要重签索引**：条目里的 `sha256` 是索引对包的承诺，包动了索引就必须重签（`--force` 覆盖）。
同样地，`-o` 指向已存在的索引要加 `--force`，避免手滑覆盖。

## 5. 使用者怎么装

```bash
# 官方目录（站点上线后：不用带任何参数）
trm install demo

# 现在（站点未上线）：用 --index 或 TRIMUM_PKG_INDEX 指到真实目录
trm install demo --index /srv/trimum/packages/index.json5
TRIMUM_PKG_INDEX=/srv/trimum/packages/index.json5 trm install demo

# 本地包（跳过分发，直接校验安装）
trm install --file dist/demo-1.0.0.trmpkg

# 看已装清单 / 卸载
trm install --list --json
trm install --remove demo --yes        # 破坏性：删目录 + 划掉登记；越界路径 / 内置 agent 一律拒
```

离线也能跑：索引与包放本地目录或 `file://` 就行，校验只依赖包内签名与内置根，不依赖 TLS。

## 6. 上线与镜像

- **静态托管即可**：把整个 `dist/`（索引 + 所有 `.trmpkg`）原样放到静态站点；`url` 是相对路径，
  换域名 / 换目录都不用改索引内容。
- **内网镜像**：复制一份到内网，`--index` 指过去即可。镜像**不需要被信任** —— 包与索引逐个对着
  内置根验签，镜像被改一个字节就会在下载后立刻失败（哈希承诺 + 签名）。
- **换默认目录地址**：站点上线后改 `src/trimum_core/pkg_install.py` 的 `DEFAULT_INDEX_URL` 一行。
  在那之前它是占位 URL，`trm install <name>` 不带 `--index` 会报下载失败（不会静默装错东西）。

## 7. 轮换根（换根 = 旧包全部作废）

1. `trm pkg root-init --out <新目录>` 造新根（**先别覆盖旧的**，留档）；
2. `trm pkg signer-init` 由新根签新签名者；
3. 用新签名者**重新打包并重签索引**（旧包链到旧根，验不过新内置根）；
4. 新 `trimum-root.crt` 提交覆盖 `config/trust/trimum-root.crt`，更新 `config/trust/README.md` 的指纹；
5. 老用户升级后：旧包一律验不过（这是设计意图，不是 bug）—— 重新安装，或临时用
   `TRIMUM_TRUST_ROOT` 指向旧根过渡。

## 8. 出问题时的对照表

| 现象 | 多半是 | 怎么办 |
|---|---|---|
| `TRM-4010` 校验失败 | 包被改过 / 签名者不在这条链上 / 内置根换过 | 看 `trm pkg verify <pkg>` 逐条列出的原因 |
| 索引缺少签名 | 索引是手写的 / 被工具重写过 | 用 `trm pkg index` 重新签一份 |
| 索引承诺的哈希与下载到的包不符 | 包被换过，或索引没跟着重签 | 重打包 → 重签索引 |
| `TRM-4011` 目录里没有 X | 名字写错，或那个包验不过（验不过就进不了索引） | `trm install --list --json` 看索引收录了什么 |
| 装上了但跑不起来 | `requires` 缺外部依赖 | 按提示装依赖，**不需要**重装包 |
| `--remove` 报 `TRM-4009` | 登记里的落地路径不是 `<type 根>/<name>`（手改过 ledger）/ 命中内置 agent | 按提示手工处理，工具故意不动手 |

## 9. 这个渠道不做什么（边界）

- **不自建包仓库**：四层生态（环境清单 / MCP / Skills / workflow 目录）才是能力来源，本渠道只决定
  「生态件如何可信地到达本机」。
- **不托管服务端**：官网服务端（域名 / 托管 / CI）属产品决策，未开工；本手册描述的是可离线复现的闭环。
- **不引入 Node 生态**：不安装 CLI-Anything 之类依赖 Node 的编排层。
- **`requires` 只探测不解决**：缺依赖只警告，装不装由用户与 `trm env install` 决定。
- **安装 ≠ 授权**：装上了不代表每一条命令都放行，运行期仍走 ToolGateway 分层 + 能力交集。
