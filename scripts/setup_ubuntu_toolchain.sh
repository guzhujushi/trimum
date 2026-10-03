#!/usr/bin/env bash
# trimum 真机开发者工具链安装（Ubuntu 24.04 noble / kernel 6.8）
#
# 用法（需 sudo，脚本**默认 dry-run**）：
#   sudo bash /tmp/setup_ubuntu_toolchain.sh                 # 只打印将要装什么（不下载）
#   sudo bash /tmp/setup_ubuntu_toolchain.sh --apply         # 装 core 档（13 个包，默认）
#   sudo bash /tmp/setup_ubuntu_toolchain.sh --apply --tier ops|all   # ops=core+运维 3 个；all=连可选档 3 个
#   sudo bash /tmp/setup_ubuntu_toolchain.sh --list          # 只列清单
#
# 设计原则：
#   - 只装**系统级**包（apt）。Python 侧依赖在两个 venv 里，属主是 guzhujushi，**不需要 sudo**。
#   - 不改 sysctl、不动 AppArmor、不重启任何服务（那些是安全策略决策，另见文档）。
#   - 幂等：已装的包直接跳过。
#   - 不用 --no-install-recommends：clang/llvm 的推荐包里有编译 BPF 需要的组件。
set -euo pipefail

APPLY=0
TIER="core"
SUDO=""

usage() {
  sed -n '2,12p' "$0"
  exit 0
}

for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    --tier) shift || true ;;
    --tier=*) TIER="${arg#--tier=}" ;;
    core|ops|optional|all) TIER="$arg" ;;
    --list) APPLY=0; TIER="all" ;;
    -h|--help) usage ;;
    *) echo "未知参数：$arg（用 --help 看用法）" >&2; exit 2 ;;
  esac
done

# 非 root 也能跑 dry-run（只读 dpkg 数据库）；只有 --apply 需要 root。
if [ "$APPLY" -eq 1 ] && [ "$(id -u)" -ne 0 ]; then
  echo "需要 root 才能安装：sudo bash $0 --apply" >&2
  exit 1
fi
if [ "$(id -u)" -ne 0 ]; then
  echo "注意：当前不是 root，只做 dry-run（不会下载）。要安装请用 sudo。" >&2
  echo
fi

# ---------------------------------------------------------------- 包清单
# core：沙箱主干 + 构建链。理由逐条在括号里。
CORE_PKGS=(
  build-essential          # gcc/g++/make（已装，幂等兜底）
  python3-dev              # Python.h：ctypes/C 扩展（已装）
  python3-venv             # 两个 venv 的前提（已装）
  pkg-config               # 几乎所有 C 构建系统的探测入口
  cmake                    # 构建 C/C++ 沙箱工具（bubblewrap/nsjail 系）
  ninja-build              # cmake/meson 的高效后端
  meson                    # 部分现代 C 项目（如 libbpf 生态例程）用它
  clang                    # 编译 eBPF C 程序 + 地址/未定义行为消毒器
  llvm                     # clang 后端与 llvm-objdump/llvm-strip（BPF 目标）
  libseccomp-dev           # seccomp 头文件（Python 侧有 libseccomp2 就够，但写 C helper 要头）
  libcap-dev               # capabilities（降权、CAP_BPF 分析）
  libbpf-dev               # 用户态 libbpf + bpf/ 头（写自己的 BPF 程序要）
  linux-tools-generic      # 版本匹配的 perf/bpftool（现装的 bpftool 已可用）
)

# ops：安全与运维（沙箱落地、可观测、审计）
OPS_PKGS=(
  shellcheck               # 仓库里脚本很多，统一 lint
  apparmor-utils           # aa-status/aa-complain/aa-genprof：查/管 AppArmor profile
  auditd                   # 内核审计（审计断链检测、syscall 级取证）
)

# optional：只有确定要走某条路线才装（不装不影响 Landlock/seccomp 主干）
OPTIONAL_PKGS=(
  uidmap                   # newuidmap/newgidmap：rootless 容器 / 用户命名空间映射前提
  fuse-overlayfs           # rootless overlay 文件系统
  golang-go                # 写 Go 辅助程序时（当前无需求）
)

select_pkgs() {
  case "$TIER" in
    core)     PKGS=("${CORE_PKGS[@]}") ;;
    ops)      PKGS=("${CORE_PKGS[@]}" "${OPS_PKGS[@]}") ;;
    optional) PKGS=("${CORE_PKGS[@]}" "${OPS_PKGS[@]}" "${OPTIONAL_PKGS[@]}") ;;
    all)      PKGS=("${CORE_PKGS[@]}" "${OPS_PKGS[@]}" "${OPTIONAL_PKGS[@]}") ;;
    *)        echo "未知 tier：$TIER" >&2; exit 2 ;;
  esac
}
select_pkgs

is_installed() { dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q "install ok installed"; }

TODO=()
for p in "${PKGS[@]}"; do
  is_installed "$p" || TODO+=("$p")
done

echo "== 目标机：$(. /etc/os-release; echo "$PRETTY_NAME") / $(uname -r)"
echo "== tier=$TIER  已装 $((${#PKGS[@]} - ${#TODO[@]})) / 共 ${#PKGS[@]}"
echo
echo "== 待安装（${#TODO[@]} 个）："
if [ "${#TODO[@]}" -eq 0 ]; then echo "   （无，全部已装）"; else printf '   %s\n' "${TODO[@]}"; fi
echo
echo "== 已装（跳过）："
for p in "${PKGS[@]}"; do is_installed "$p" && echo "   $p $(dpkg-query -W -f='${Version}' "$p" 2>/dev/null)"; done
echo

if [ "$APPLY" -ne 1 ]; then
  echo "== dry-run：未下载任何东西。要真装请加 --apply"
  echo "   sudo bash $0 --apply$([ "$TIER" != core ] && echo " --tier $TIER")"
  exit 0
fi

if [ "${#TODO[@]}" -eq 0 ]; then
  echo "== 没有需要安装的包，退出（未跑 apt-get update）"
  exit 0
fi

echo "== apt-get update"
DEBIAN_FRONTEND=noninteractive apt-get update

echo "== apt-get install -y ${TODO[*]}"
DEBIAN_FRONTEND=noninteractive apt-get install -y "${TODO[@]}"

echo
echo "== 安装后核对"
for p in "${TODO[@]}"; do
  printf '   %-22s %s\n' "$p" "$(dpkg-query -W -f='${Version}' "$p" 2>/dev/null || echo '仍缺失')"
done

echo
echo "== 工具自检"
for b in gcc clang make cmake meson ninja pkg-config shellcheck aa-status auditctl bpftool perf; do
  printf '   %-14s %s\n' "$b" "$(command -v "$b" || echo '（无）')"
done

cat <<'NEXT'

== 下一步（都不需要 sudo）
   1) Python 侧依赖：两份 venv 属主是 guzhujushi，直接装——
        /home/guzhujushi/trimum/.venv/bin/python -m pip install -r <...>
        /opt/trimum/venv/bin/python      -m pip install <pkg>
   2) 沙箱能力自检：bash /tmp/check_sandbox_caps.sh
   3) 安全策略类改动（sysctl / AppArmor / systemd 单元）**不在此脚本内**，见 docs/SANDBOX-PLAN.md 的待裁决项。
NEXT