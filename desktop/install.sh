#!/usr/bin/env bash
# =============================================================================
# trimum — Arch Linux 桌面安装脚本（参考 Omarchy / Arch 官方安装流程）
#
# 用法:
#   sudo bash desktop/install.sh /dev/sdX      # X = 目标磁盘（nvme0n1 亦可）
#
# 流程:
#   1. 分区: GPT + Btrfs 子卷 @ / @home / @snapshots + EFI 分区
#   2. pacstrap 基础系统 + 桌面/工具软件包
#   3. 生成 fstab（UUID）
#   4. 配置 Snapper（调用 scripts/setup-btrfs-snapper.sh）
#   5. 安装桌面/工具软件包（与第 2 步合并，见 PACKAGES）
#   6. 创建用户并拷贝 dotfiles 到 ~/.config
#   7. 安装 trimum Python 包（pip install /opt/trimum/src/trimum-mvp）
#   8. 提示配置 API Key（写入 ~/.trimum/env）
#   9. 启用服务（NetworkManager / bluetooth / pipewire）
#   10. 设置 zsh 为默认 shell + 安装 GRUB 引导
#
# 注意: 这是一个"起点"脚本，真机安装前请按需调整
#       （磁盘、用户名、时区、分区大小、是否加密等）。
# 要求: 在 Arch Live ISO（UEFI 模式）下以 root 运行，且已联网。
# =============================================================================
set -euo pipefail

# ---- 可配置变量（可用环境变量覆盖）----
DISK="${1:-}"                              # 目标磁盘, 如 /dev/nvme0n1
ESP_SIZE_MIB="${TRIMUM_ESP_MIB:-1024}"     # EFI 分区大小
USERNAME="${TRIMUM_USER:-trimum}"          # 用户名
HOSTNAME="${TRIMUM_HOSTNAME:-trimum}"      # 主机名
TIMEZONE="${TRIMUM_TIMEZONE:-Asia/Shanghai}"
LOCALE="${TRIMUM_LOCALE:-en_US.UTF-8}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ---- 工具函数 ----
die() { printf '\033[1;31m[install]\033[0m %s\n' "$*" >&2; exit 1; }
info() { printf '\033[1;34m[install]\033[0m %s\n' "$*"; }
ok() { printf '\033[1;32m[install]\033[0m %s\n' "$*"; }
need() { command -v "$1" >/dev/null 2>&1 || die "缺少命令: $1（请安装后在 Arch Live 环境重试）"; }

# ---- 软件包列表 ----
# 基础系统 + 任务指定桌面/工具包；额外依赖均有注释说明
BASE_PACKAGES=(base base-devel linux linux-firmware sudo git python python-pip)

DESKTOP_PACKAGES=(
  # 任务指定
  hyprland waybar kitty wofi swww
  polkit-kde-agent cliphist
  pipewire pipewire-pulse wireplumber
  networkmanager bluez bluez-utils blueman
  starship zsh neovim ripgrep fd btop jq
  # 快捷键/脚本所需（hyprland.conf 绑定、壁纸、剪贴板）
  grim slurp wl-clipboard brightnessctl playerctl
  # 系统/引导/快照
  btrfs-progs snapper grub efibootmgr
  # 字体与 XDG 门户（waybar/kitty 渲染、截图分享）
  ttf-jetbrains-mono-nerd noto-fonts noto-fonts-cjk noto-fonts-emoji
  xdg-desktop-portal-hyprland xdg-desktop-portal-gtk
)

# ---- 1. 前置检查 ----
[ "$(id -u)" -eq 0 ] || die "请以 root 运行: sudo bash desktop/install.sh /dev/sdX"
[ -n "$DISK" ] || die "用法: sudo bash desktop/install.sh /dev/sdX"
[ -b "$DISK" ] || die "不是块设备: $DISK"
findmnt "$DISK" >/dev/null 2>&1 && die "磁盘已被挂载，拒绝操作: $DISK"
findmnt /mnt >/dev/null 2>&1 && die "/mnt 已被占用，请先卸载"
need pacstrap; need arch-chroot; need sgdisk; need mkfs.fat; need mkfs.btrfs; need partprobe

read -r -p "将【清空并重新分区】$DISK 并安装 Arch，继续? [y/N] " confirm
[[ "$confirm" =~ ^[Yy]$ ]] || { info "已取消"; exit 1; }

# ---- 2. 分区（GPT: EFI + Btrfs）----
PART_SUFFIX=""
[[ "$DISK" =~ [0-9]$ ]] && PART_SUFFIX="p"   # nvme0n1 -> nvme0n1p1
EFI_PART="${DISK}${PART_SUFFIX}1"
ROOT_PART="${DISK}${PART_SUFFIX}2"

info "分区: $DISK（EFI=${ESP_SIZE_MIB}MiB @ $EFI_PART, Btrfs @ $ROOT_PART）"
wipefs -a "$DISK" || true
sgdisk --zap-all "$DISK"
partprobe "$DISK"; udevadm settle || true
sgdisk -n "1:0:+${ESP_SIZE_MIB}M" -t 1:ef00 -n "2:0:0" -t 2:8304 "$DISK"
partprobe "$DISK"; udevadm settle || true
sleep 1

info "格式化 $EFI_PART (FAT32) 与 $ROOT_PART (Btrfs)"
mkfs.fat -F32 "$EFI_PART"
mkfs.btrfs -f "$ROOT_PART"

# ---- 3. Btrfs 子卷: @ / @home / @snapshots ----
info "创建 Btrfs 子卷: @ / @home / @snapshots"
mount "$ROOT_PART" /mnt
btrfs subvolume create /mnt/@
btrfs subvolume create /mnt/@home
btrfs subvolume create /mnt/@snapshots
umount /mnt

mount -o subvol=@,compress=zstd,noatime "$ROOT_PART" /mnt
mkdir -p /mnt/home /mnt/.snapshots /mnt/boot
mount -o subvol=@home,compress=zstd,noatime "$ROOT_PART" /mnt/home
mount -o subvol=@snapshots,compress=zstd,noatime "$ROOT_PART" /mnt/.snapshots
mount "$EFI_PART" /mnt/boot

# ---- 4. pacstrap 基础系统 + 软件包 ----
info "pacstrap 基础系统 + 软件包（需联网，耗时较长）..."
pacstrap -K /mnt "${BASE_PACKAGES[@]}" "${DESKTOP_PACKAGES[@]}"

info "生成 fstab"
genfstab -U /mnt >> /mnt/etc/fstab
[ -s /mnt/etc/fstab ] || die "fstab 生成失败"

# ---- 5. 拷贝仓库到目标系统 /opt/trimum ----
info "拷贝 trimum 仓库 -> /mnt/opt/trimum"
mkdir -p /mnt/opt/trimum
cp -a "$REPO_ROOT/." /mnt/opt/trimum/
# 确保脚本可执行（Windows 检出/提交可能丢失 +x 位）
chmod +x /mnt/opt/trimum/scripts/trimum-theme \
  /mnt/opt/trimum/desktop/install.sh \
  /mnt/opt/trimum/desktop/dotfiles/hypr/wallpaper.sh

# ---- 6-10. chroot 内配置 ----
info "进入 chroot 配置系统..."
cat > /mnt/root/trimum-setup.sh <<'TSEOF'
#!/usr/bin/env bash
set -euo pipefail
USERNAME="$1"; HOSTNAME="$2"; TIMEZONE="$3"; LOCALE="$4"; TRIMUM_HOME="$5"

info()  { printf '\033[1;34m[setup]\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m[setup]\033[0m %s\n' "$*"; }

# 时区与硬件时钟
ln -sf "/usr/share/zoneinfo/$TIMEZONE" /etc/localtime
hwclock --systohc

# locale（en_US + zh_CN）
sed -i 's/^#\(en_US\.UTF-8\)/\1/; s/^#\(zh_CN\.UTF-8\)/\1/' /etc/locale.gen
locale-gen
echo "LANG=${LOCALE}" > /etc/locale.conf

# hostname
echo "$HOSTNAME" > /etc/hostname
cat > /etc/hosts <<'HEOF'
127.0.0.1   localhost
::1         localhost
127.0.1.1   HOSTNAME.localdomain HOSTNAME
HEOF
sed -i "s/HOSTNAME/$HOSTNAME/g" /etc/hosts

# initramfs + GRUB（UEFI）
info "mkinitcpio + GRUB 引导"
mkinitcpio -P
grub-install --target=x86_64-efi --efi-directory=/boot --bootloader-id=GRUB
grub-mkconfig -o /boot/grub/grub.cfg

# 用户（wheel 等组，默认 zsh）
if id "$USERNAME" >/dev/null 2>&1; then
  info "用户 $USERNAME 已存在，跳过创建"
else
  useradd -m -G wheel,audio,video,input,storage,network,power -s /usr/bin/zsh "$USERNAME"
fi
echo "== 设置用户 $USERNAME 的密码 =="
passwd "$USERNAME"
echo "== 设置 root 密码 =="
passwd root
sed -i 's/^# *%wheel ALL=(ALL:ALL) ALL/%wheel ALL=(ALL:ALL) ALL/' /etc/sudoers

# 拷贝 dotfiles 到 ~/.config（hypr/kitty/waybar/wofi/alacritty）
info "拷贝 dotfiles -> /home/$USERNAME/.config"
CONFIG="/home/$USERNAME/.config"
mkdir -p "$CONFIG"
for app in hypr kitty waybar wofi alacritty; do
  [ -d "$TRIMUM_HOME/desktop/dotfiles/$app" ] || continue
  cp -a "$TRIMUM_HOME/desktop/dotfiles/$app" "$CONFIG/"
done
# 壁纸目录直接链接到仓库（保持单一数据源）
ln -sfn "$TRIMUM_HOME/desktop/dotfiles/wallpapers" "$CONFIG/wallpapers"
# 入口链接: current 由 scripts/trimum-theme 维护
ln -sfn current/hyprland.conf "$CONFIG/hypr/hyprland.conf"
ln -sfn current/kitty.conf   "$CONFIG/kitty/kitty.conf"
ln -sfn current/style.css    "$CONFIG/waybar/style.css"
chown -R "$USERNAME:$USERNAME" "$CONFIG"

# zsh 集成（ai() 函数 + PATH）
cp "$TRIMUM_HOME/desktop/zsh-ai.sh" "/home/$USERNAME/.config/zsh-ai.sh"
grep -q 'zsh-ai.sh' "/home/$USERNAME/.zshrc" 2>/dev/null || cat >> "/home/$USERNAME/.zshrc" <<'ZRC'

# trimum AI Shell 集成
export TRIMUM_HOME="/opt/trimum"
export PATH="$TRIMUM_HOME/scripts:$PATH"
[ -f ~/.config/zsh-ai.sh ] && source ~/.config/zsh-ai.sh
ZRC
chown "$USERNAME:$USERNAME" "/home/$USERNAME/.config/zsh-ai.sh" "/home/$USERNAME/.zshrc"

# 安装 trimum Python 包（仓库根无 pyproject 时安装 src/trimum-mvp）
info "安装 trimum Python 包"
if [ -f "$TRIMUM_HOME/pyproject.toml" ]; then
  pip install "$TRIMUM_HOME"
else
  pip install "$TRIMUM_HOME/src/trimum-mvp"
fi

# API Key（写入 ~/.trimum/env，chmod 600）
ENVDIR="/home/$USERNAME/.trimum"
mkdir -p "$ENVDIR"
if [ -f "$ENVDIR/env" ]; then
  info "已存在 $ENVDIR/env，跳过 API Key 配置"
else
  echo "== 配置 trimum API Key（写入 $ENVDIR/env）=="
  read -r -p "API Key（留空跳过）: " apikey
  read -r -p "Base URL（默认 https://api.deepseek.com/v1）: " baseurl
  : > "$ENVDIR/env"
  [ -n "$apikey" ] && echo "TRIMUM_API_KEY=$apikey" >> "$ENVDIR/env"
  [ -n "$baseurl" ] && echo "TRIMUM_BASE_URL=$baseurl" >> "$ENVDIR/env"
fi
chown -R "$USERNAME:$USERNAME" "$ENVDIR"
chmod 600 "$ENVDIR/env"

# 服务: NetworkManager / bluetooth / PipeWire 用户服务
info "启用系统服务"
systemctl enable NetworkManager.service bluetooth.service

PW_USER="/home/$USERNAME/.config/systemd/user"
mkdir -p "$PW_USER/default.target.wants"
for unit in pipewire.socket pipewire-pulse.socket wireplumber.service; do
  if [ -f "/usr/lib/systemd/user/$unit" ]; then
    ln -sf "/usr/lib/systemd/user/$unit" "$PW_USER/default.target.wants/$unit"
  fi
done
chown -R "$USERNAME:$USERNAME" "/home/$USERNAME/.config/systemd"
touch "/var/lib/systemd/linger/$USERNAME"   # 允许用户服务开机自启

# Snapper（调用仓库脚本；使用 snapper 默认模板）
info "配置 Snapper"
export OMARCHY_SNAPPER_TEMPLATE="/etc/snapper/config-templates/default"
bash "$TRIMUM_HOME/scripts/setup-btrfs-snapper.sh"

# 默认 shell
chsh -s /usr/bin/zsh "$USERNAME"

ok "chroot 配置完成"
TSEOF

arch-chroot /mnt bash /root/trimum-setup.sh "$USERNAME" "$HOSTNAME" "$TIMEZONE" "$LOCALE" "/opt/trimum"

# ---- 收尾 ----
info "卸载分区"
umount -R /mnt

cat <<EOF

==========================================================
 trimum Arch 安装完成！
==========================================================
 1) 重启:   reboot
 2) 登录:   用户 $USERNAME（密码已设置）
 3) 进入桌面: 在 tty 登录后执行  Hyprland
    （如需图形登录管理器，可后续安装 sddm）
 4) 主题切换: trimum-theme list / set <name> / preview <name>
 5) API Key 可稍后编辑: ~/.trimum/env
==========================================================
EOF
