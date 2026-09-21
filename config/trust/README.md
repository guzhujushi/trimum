# config/trust —— 官方信任锚

本目录放**官方根证书**（`trimum-root.crt`，JSON 文档：`role: root` + Ed25519 公钥 + `key_id`）。
它是 `trmpkg.verify_package()` 的信任锚：包里的证书链必须能追到这把公钥。

- **只提交公钥证书**。根私钥与签发者私钥属于发布方（官网签名机 / 自己的发布账号），
  永不进仓库；测试用 `trmpkg.make_root()` / `make_signer_cert()` 在临时目录现生成。
- 运行态查找顺序：`TRIMUM_TRUST_ROOT` 环境变量 → `~/.trimum/trust/trimum-root.crt`
  → 本仓库目录（开发态）。
- `trm pkg root-init` / `signer-init` 拒绝把私钥写进 git 工作树
  （只有显式 `--insecure-key-output` 才放行）——见 `src/trimum_core/cli/commands/pkg.py`。

## 当前这把根（2026-09-21 生成）

| 项 | 值 |
|---|---|
| 名称 | `trimum-root` |
| 算法 | Ed25519 |
| key_id | `sha256:65da4663034583915402dd107ea7b0914d1d37fb936cb67c5fa7e67d07092565` |
| 生成时间 | 2026-09-21T07:07:48Z |
| 私钥位置 | 发布方本机 `~/.trimum/trust/trimum-root.key`（**不在仓库**；丢了就只能换根重签所有包） |

发布方的签名者证书 `trimum-release`（key_id `sha256:2dff2c90…`）由这把根签发，存在发布方
`~/.trimum/trust/signers/`；`.trmpkg` 的 `chain.json` 里带的就是它（[签名者, 根]）。

## 发布流程（`trm pkg`）

```bash
# ① 首次：造根（只在官方发布机上做一次，私钥另存备份）
trm pkg root-init                                  # → ~/.trimum/trust/trimum-root.{crt,key}

# ② 造签名者证书（官网发版用；能力清单写在这里，运行期只收紧策略）
trm pkg signer-init --name trimum-release --tools '*' --max-risk inherit

# ③ 打包官方产物
trm pkg create ./agents/demo -o dist/demo-1.0.0.trmpkg --type agent --version 1.0.0 \
  --signer-cert ~/.trimum/trust/signers/trimum-release.crt \
  --key ~/.trimum/trust/signers/trimum-release.key

# ④ 使用者侧（不需要任何参数：默认就用内置根）
trm pkg verify dist/demo-1.0.0.trmpkg
```

## 换根（轮换）

`root-init` 只管「有没有」，不认「是不是同一把」：换根 = `root-init --force` 重新生成
→ 提交新证书 → 用新根重签签名者证书 → **所有旧包作废**（链追不到新根）。
换根时记得同步更新本文件的指纹与 `docs/ECOSYSTEM-STRATEGY.md` §7.5。

见 `docs/ECOSYSTEM-STRATEGY.md` §7.4 / §7.5。