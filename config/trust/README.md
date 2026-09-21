# config/trust —— 官方信任锚

本目录放**官方根证书**（`trimum-root.crt`，JSON 文档：`role: root` + Ed25519 公钥 + `key_id`）。
它是 `trmpkg.verify_package()` 的信任锚：包里的证书链必须能追到这把公钥。

- **只提交公钥证书**。根私钥与签发者私钥属于发布方（官网签名机 / 自己的发布账号），
  永不进仓库；测试用 `trmpkg.make_root()` / `make_signer_cert()` 在临时目录现生成。
- 运行态查找顺序：`TRIMUM_TRUST_ROOT` 环境变量 → `~/.trimum/trust/trimum-root.crt`
  → 本仓库目录（开发态）。
- 生成命令（`trm pkg root-init`）随 E5 下一片落地；在那之前本目录是空的，
  `verify_package()` 会明确报「找不到内置根证书」，而不是把包当成验过了。

见 `docs/ECOSYSTEM-STRATEGY.md` §7.4。