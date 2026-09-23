#!/usr/bin/env bash
# browse 安装（真机，零 sudo）：headless Chromium + ~/bin/browse
#
# 用法（真机）：
#   bash scripts/install_browse.sh          # 已装就只更新 browse.mjs / ~/bin/browse
#
# 装了什么（全在用户目录，不动系统）：
#   ~/.local/share/browse/node_modules/playwright   npm 包
#   ~/.cache/ms-playwright/chromium-*               Chromium（约 114MB，只下 chromium，不下 firefox/webkit）
#   ~/.local/share/browse/browse.mjs                实现
#   ~/bin/browse                                    入口
#
# 为什么不用系统包：真机 sudo 要口令（agent 不代跑），而 Playwright 自带 Chromium，
#   且 Ubuntu 24.04 的 chromium 是 snap、firefox 也是 snap，塞进无桌面环境更麻烦。
# 为什么必须 --no-sandbox：Ubuntu 24.04 默认 kernel.apparmor_restrict_unprivileged_userns=1，
#   非 snap 的 Chromium 拿不到 user namespace（browse.mjs 里已带）。
set -uo pipefail

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="$SELF_DIR/browse.mjs"
[ -f "$SRC" ] || SRC=/tmp/browse.mjs

PREFIX="$HOME/.local/share/browse"
mkdir -p "$PREFIX" "$HOME/bin" "$HOME/trimum/tmp/browse-out"

command -v node >/dev/null || { echo "缺 node，先跑 scripts/setup_ubuntu_toolchain.sh"; exit 1; }
echo "node: $(node -v)  npm: $(npm -v)"

# 代理：优先本机 mihomo（装包要从 github/npm 拉）
PROXY=""
if timeout 3 bash -c 'cat < /dev/null > /dev/tcp/127.0.0.1/7890' 2>/dev/null; then
  PROXY="http://127.0.0.1:7890"
  export HTTPS_PROXY="$PROXY" HTTP_PROXY="$PROXY"
  echo "下载代理: $PROXY"
else
  echo "下载代理: 无（direct）"
fi

echo "===== 1) npm i playwright（跳过大体积浏览器下载）====="
cd "$PREFIX" || exit 1
export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
[ -f package.json ] || npm init -y >/dev/null 2>&1
npm i playwright --no-audit --no-fund 2>&1 | tail -3

echo "===== 2) npx playwright install chromium ====="
unset PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD
npx playwright install chromium 2>&1 | tail -4

echo "===== 3) 安装 browse.mjs 与 ~/bin/browse ====="
cp "$SRC" "$PREFIX/browse.mjs"
chmod 755 "$PREFIX/browse.mjs"
cat > "$HOME/bin/browse" <<'EOF'
#!/usr/bin/env bash
# browse —— 无桌面环境下的浏览器（headless Chromium / Playwright，零 sudo）
# 用法: browse [--proxy|--direct] [--mobile] [--wait ms] [--full|--viewport] shot|text|dom|pdf <URL> [输出]
#   --proxy : 走本机 mihomo (127.0.0.1:7890) 出网，用于 google/github 等境外站
# 产物默认落 ~/trimum/tmp/browse-out/（T2 默认打开的目录，手机在 vscode web 里可直接预览）
set -u
exec /usr/bin/env node "$HOME/.local/share/browse/browse.mjs" "$@"
EOF
chmod 755 "$HOME/bin/browse"

echo "===== 4) 自测 ====="
timeout 90 "$HOME/bin/browse" --direct text https://example.com 2>&1 | tail -5
echo
echo "OK. 用法: ~/bin/browse shot https://example.com   |   ~/bin/browse --proxy text https://github.com"
