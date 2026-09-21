# 多用户边界 —— 现状、方案与迁移成本（E5 第三片步骤 3）

> 性质：**调研 + 设计，不含实现**（`TODO.md`「E5 第三片实施计划」步骤 3 的要求）。
> 来源：`docs/ECOSYSTEM-STRATEGY.md` §7.2 的三个未决子问题 ——
> ① `/etc/trimum/`（系统公共）与 `~/.trimum/`（用户私有）的边界；② 审计日志的 `user_id` 归属；
> ③ 私钥保护（文件权限 / DPAPI / keyring）。
> 复核结论：**现有设计没有硬伤**（单点干净、隔离天然成立），因此本步骤**不改代码**；
> 唯一的「值得现在就记一笔」是 Windows 上 `chmod` 不产生 ACL（见 §4）。

---

## 0. 一句话结论

trimum 今天是**单用户家目录模型**，而且「每用户一份」是**结构上成立**的，不是散落的路径拼接：
`paths.trimum_home()` 是数据根的唯一改点，`identity.py` 是身份的唯一改点，`Config` 的 XDG 路径
是配置 / 日志的唯一改点，IPC socket 已经按 uid 分目录。

缺的**不是隔离**（家目录天然隔离），而是三层里的第三层：**系统公共层**（共享信任根 / 共享策略基线）
与**归属**（审计里「谁做的」）。所以顺序是：**先定规则（本文档），再写实现**；
真要动手时的建议顺序 = 审计归属 → 系统公共层只读挂载 → 私钥保护。

## 1. 现状清单（代码事实，逐条可查）

| 关注点 | 今天在哪 | 关键实现 | 多用户下会怎样 |
|---|---|---|---|
| 用户数据根 | `~/.trimum/` | `paths.trimum_home()`（`TRIMUM_HOME` 可覆盖） | 家目录天然每用户一份 ✓ |
| 用户身份私钥 | `~/.trimum/identity/identity-ed25519.key` | `identity.generate_identity()`，POSIX `chmod 0600` | POSIX 够用；Windows 上 `chmod` 是空操作（§4） |
| agent 证书 | `~/.trimum/agents/<name>/cert.json`、`~/.trimum/certs/{official,trusted}/` | `agent_cert.check_agent_trust()`（文件夹自带优先） | 每用户一份 ✓；「内置 agent 的官方签发」与「本机信任」现在混在同一层 |
| 配置 / 策略 | `~/.config/trimum/{config,policy}.yaml`（XDG） | `config.py`；`--config /etc/trimum/config.yaml` 已经能用 | 有系统级配置的入口，但没有「系统默认 + 用户覆盖」的合并规则 |
| 日志 / 审计 / 上下文 | `~/.local/share/trimum/{trimum.log,audit.jsonl,context.db}` | `audit_store.default_audit_path()` | 每用户一份 ✓；代价是**共享机器上看不到「这台机器整体发生了什么」** |
| 运行时 socket | `$XDG_RUNTIME_DIR/trimum.sock` → `/run/user/<uid>/trimum.sock` | `config.default_socket_path()`（按 uid） | 已经是 per-uid ✓（好先例：这层不用重做） |
| 审计字段 | `AuditEvent`：agent / tool / command / risk / action / jit… | `models.AuditEvent` | **没有 `user_id`**：多用户下分不清是谁（§3） |
| 共享只读资产 | 仓库 `config/trust/trimum-root.crt`、`/opt/trimum/agents` | `trmpkg.default_root_path()`、`agent_cert.bundled_agent_dirs()` | 已有「公共资产」雏形，但**没有 `/etc/trimum` 这一层**：现在只能靠「装到哪里」碰运气 |
| 权限判定 | `env_toolchain._is_root()`（`os.geteuid()==0`）、`capability.py` 运行期交集 | — | 没有「这个用户能不能装系统包 / 写公共层」的统一口径 |
| 包登记（E5） | `~/.trimum/config/installed.json5` | `pkg_install.load_ledger()` | 每用户一份 ✓；共享安装（`/etc/trimum`）会需要第二张账（见 §2） |

## 2. 问题①：`/etc/trimum/`（系统公共） vs `~/.trimum/`（用户私有）

**原则**：公共层只放「所有人可读、只有 root 可写」的东西；**任何带私钥的东西一律不进公共层**。

| 内容 | 建议归属 | 理由 |
|---|---|---|
| 官方信任根 `trimum-root.crt` | 公共层 `/etc/trimum/trust/`（保留内置兜底） | 本来就是公开公钥、随发行包分发；多用户共用一份，换根只改一处 |
| 系统级策略基线 `policy.yaml` | 公共层 `/etc/trimum/policy.yaml` | 管理员统一收紧；用户策略**只能再收紧**（沿用「能力只收紧」的既有口径） |
| 系统级配置基线 `config.yaml` | 公共层 `/etc/trimum/config.yaml` | `--config` 入口已存在，缺的是「系统默认 → 用户覆盖」的合并顺序 |
| 共享安装的包（可选） | 公共层 `/etc/trimum/{agents,tools,workflows,skills}/` | 要 root 才能写；用户私有安装仍进 `~/.trimum/<type>/` |
| 用户身份私钥 / agent 证书 / memory / learning / audit | **只能用户层** | 带私钥、带个人数据 |
| 用户自装的 tool / skill / workflow | 用户层 | 用户自治，不该要求 root |

**查找顺序（建议）**：`~/.trimum/<type>/` → `/etc/trimum/<type>/` → 内置（发行包）。
同名以**用户层为准**，公共层只补空缺 —— 与 `agent_cert.check_agent_trust()` 的「文件夹自带优先」
同一套直觉，用户永远能用一个自己的版本覆盖系统版本，反之不行。

**登记的第二个账本**：公共层安装需要 root，登记不能写进用户 `installed.json5`。
建议公共层用 `/etc/trimum/config/installed.json5`（同样的 `trminstall/1` 格式），
`trm install --list` 同时读两处并标注来源（`system` / `user`）；`--remove` 只允许删本用户账本里的条目
（删系统条目要 root，且属于管理动作，不能由普通用户触发）。

**迁移成本**：低。`paths.py` 加一个 `system_home()`（`TRIMUM_SYSTEM_HOME` 可覆盖，便于测试与容器），
三处查找从「单路径」改成「有序列表」；**写入路径一个都不动**。

## 3. 问题②：审计日志的 `user_id` 归属

现状：`AuditEvent` 没有用户字段；审计写在用户自己的 `~/.local/share/trimum/audit.jsonl`。
两个极端都不对：各写各的 → 管理员看不到全貌；一律写 `/var/log` → daemon 得跑 root，
和「审计是旁路、写失败不影响执行」的现有取舍冲突。

**建议（三步，可各自独立落地）**

1. **加字段**：`AuditEvent.user_id`（用户名 + uid；Windows 用 username/SID）+ `machine_id`，
   取值复用 `identity.user_name()` 的口径（`TRIMUM_USER` → `USER`/`USERNAME` → `getpass`）。
   纯增字段、向后兼容（老记录读到空串），并顺手让 `trm log audit` 能按 `--user` 过滤。
2. **分流**：默认仍写用户自己的文件；允许配置 / `--audit <path>` 指向共享文件
   （管理员把它设成 `/var/log/trimum/audit.jsonl` 并给组写权限）—— 谁想集中就集中，不强制。
3. **系统模式校验**：daemon 以 root 跑时给每个连接打上 `peer_uid`（Linux `SO_PEERCRED`；
   Windows 命名管道取客户端 SID），与事件里的 `user_id` 交叉校验 —— 防「用户自己填别人的名字」。

**不做**：不把审计整体搬去系统目录（会破坏「旁路」取舍），也不引入中心化采集/上报。

## 4. 问题③：私钥保护（文件权限 / DPAPI / keyring）

现状：POSIX `chmod 0600`（`identity.generate_identity()`、`pkg._write_private_key()`）。
**Windows 上 `chmod` 不产生 ACL**：私钥对同机其他用户可读。三档方案：

| 方案 | 平台 | 成本 | 取舍 |
|---|---|---|---|
| A. 现状 + 显式告警 | 全平台 | 最低 | Windows 上等于没保护；只适合「单用户个人机」 |
| B. 文件权限收紧（目录 0700 + 文件 0600；Windows 用 ACL / `icacls`） | 全平台 | 中 | 覆盖绝大多数场景；Windows 要处理 ACL 继承与「设不上就告警」的回退 |
| C. 系统 keyring / DPAPI / macOS Keychain（`keyring` 包） | 全平台 | 高（新依赖 + 迁移） | 最强；但要新增「keyring 不可用时怎么办」的降级策略，会把「裸安装也能跑完」这条现有承诺变复杂 |

**建议**：先 **B**，把 **C 作为可选后端**（`identity` 里加一个后端开关：优先 keyring，
取不到就回退文件并告警）。理由：B 不引依赖、可测试；C 值得做，但不该成为前置条件。

**红线（无论哪档）**：私钥不进公共层、不进仓库、不进日志；`trm pkg root-init` / `signer-init` 的
「拒绝把私钥写进 git 工作树」守卫继续有效，keyring 后端也保留同样的拒绝语义（写进 keyring ≠ 可以绕过守卫）。

## 5. 不变量（多用户实现时不能破的）

- **安装 ≠ 授权**：来源可信不改变运行期策略；公共层里的包也照走 ToolGateway 分层。
- **能力只收紧**：运行期取 `用户策略 ∩ 系统策略 ∩ 证书能力` 的最严结论，系统层只能收紧用户层。
- **自签身份绑定 machine + user**：换人 / 换机自动失效，必须重新自签（不是「导入」）。
- **审计是旁路**：写失败返回 False，绝不拖垮执行路径。
- **公共层只读**：用户进程不写 `/etc/trimum`；要写就走 `sudo` + 脚本（`AGENTS.md` 的 sudo 规则）。
- **单点不被绕过**：数据根只有 `paths.trimum_home()` / `system_home()` 两个入口，
  新增代码不许自己拼 `Path.home()/".trimum"`。

## 6. 真要动手时的顺序与风险

| 步骤 | 改动面 | 风险 |
|---|---|---|
| 1. 审计 `user_id` + `machine_id` | `models.AuditEvent` 加字段、`identity.user_name()` 复用、`trm log audit --user` | 低（纯增字段，加断言即可） |
| 2. `paths.system_home()` + 三处查找改有序列表 | `paths.py`、`agent_cert.check_agent_trust`、`trmpkg.default_root_path` | 中（查找顺序变化，需要「用户层优先」的测试钉住） |
| 3. 私钥后端 B（目录 0700 / Windows ACL） | `identity.py`、`pkg._write_private_key`；`trm doctor` 加一条私钥权限检查 | 中（平台差异） |
| 4. 系统模式 `peer_uid` 校验 | `ipc_handler` / `api_server` 连接层 | 中（Linux-only；Windows 走命名管道 SID） |
| 5. keyring 后端（可选） | `identity.py` + 打包依赖 + 降级策略 | 高（新依赖与新失败模式） |

## 7. 本轮明确不做

- **不动任何代码**（计划要求；复核后未发现硬伤）。
- 不做用户账号体系、权限管理界面、团队共享 —— 那是产品决策，不在本步骤范围。
- 不改 `TRIMUM_HOME` 语义（测试与 provisioning 都依赖它）。
