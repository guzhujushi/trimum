#!/bin/bash
# Trimum Ubuntu Desktop — One-command install
# Usage: bash <(curl -fsSL https://...)  or  curl -fsSL https://... | bash
#
# Inspired by Omakub/Omabuntu, designed for Ubuntu 24.04 LTS (Noble)

set -euo pipefail
IFS=$'\n\t'

# ──────────────────────────────────────────────
#  Colors
# ──────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail()  { echo -e "${RED}[FAIL]${NC} $*"; exit 1; }

# ──────────────────────────────────────────────
#  Pre-flight checks
# ──────────────────────────────────────────────
check_preflight() {
    info "Checking system requirements..."

    # OS check
    if [ ! -f /etc/os-release ]; then
        fail "Not a Linux system with /etc/os-release"
    fi
    . /etc/os-release
    if [ "$ID" != "ubuntu" ]; then
        fail "This installer is for Ubuntu. Detected: $ID"
    fi

    # Version check (24.04+)
    major_ver=$(echo "$VERSION_ID" | cut -d. -f1)
    minor_ver=$(echo "$VERSION_ID" | cut -d. -f2)
    if [ "$major_ver" -lt 24 ]; then
        fail "Ubuntu 24.04+ required. Detected: $VERSION_ID"
    fi

    # Architecture
    if [ "$(uname -m)" != "x86_64" ]; then
        fail "x86_64 required. Detected: $(uname -m)"
    fi

    # Internet connectivity
    if ! ping -c 1 -W 2 archive.ubuntu.com &>/dev/null; then
        fail "No internet connectivity detected"
    fi

    ok "System: $PRETTY_NAME ($(uname -m))"
}

# ──────────────────────────────────────────────
#  Install system packages
# ──────────────────────────────────────────────
install_base_packages() {
    info "Installing base packages..."

    # Update package lists
    sudo apt-get update -qq

    # Install from the package list
    # shellcheck source=install/trimum-base.packages
    while IFS= read -r pkg || [ -n "$pkg" ]; do
        # Skip comments and blank lines
        [[ "$pkg" =~ ^#.*$ || -z "$pkg" ]] && continue
        sudo apt-get install -y -qq "$pkg" 2>/dev/null || warn "Package '$pkg' not found, skipping"
    done < "$(dirname "$0")/install/trimum-base.packages"

    ok "Base packages installed"
}

# ──────────────────────────────────────────────
#  Install Flatpak apps & GNOME extensions
# ──────────────────────────────────────────────
install_flatpak_apps() {
    info "Installing Flatpak apps..."

    # Ensure Flathub is added
    flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo

    while IFS= read -r app || [ -n "$app" ]; do
        [[ "$app" =~ ^#.*$ || -z "$app" ]] && continue
        flatpak install -y flathub "$app" 2>/dev/null || warn "Flatpak '$app' failed"
    done < "$(dirname "$0")/install/trimum-flatpak.packages"

    ok "Flatpak apps installed"
}

# ──────────────────────────────────────────────
#  Apply GNOME settings
# ──────────────────────────────────────────────
apply_gnome_settings() {
    info "Applying GNOME settings..."

    # Source GNOME settings file
    if [ -f "$(dirname "$0")/config/gnome-settings.conf" ]; then
        # shellcheck source=config/gnome-settings.conf
        source "$(dirname "$0")/config/gnome-settings.conf"
    fi

    ok "GNOME settings applied"
}

# ──────────────────────────────────────────────
#  Apply theme
# ──────────────────────────────────────────────
apply_theme() {
    local theme="${1:-catppuccin}"
    info "Applying theme: $theme..."

    local theme_dir="$(dirname "$0")/themes/$theme"
    if [ ! -d "$theme_dir" ]; then
        warn "Theme '$theme' not found, skipping"
        return
    fi

    # Apply colors
    if [ -f "$theme_dir/colors.conf" ]; then
        # shellcheck source=themes/"$theme"/colors.conf
        source "$theme_dir/colors.conf"
    fi

    # Apply GNOME Shell theme via gnome-extensions if available
    # Install system GTK theme if bundled

    ok "Theme '$theme' applied"
}

# ──────────────────────────────────────────────
#  Setup developer tools
# ──────────────────────────────────────────────
setup_dev_tools() {
    info "Setting up developer tools..."

    # Install Trimum core
    if [ -d "$HOME/.trimum" ]; then
        info "Trimum home already exists at ~/.trimum"
    fi

    # Set up starship
    if command -v starship &>/dev/null; then
        mkdir -p "$HOME/.config"
        cp "$(dirname "$0")/config/starship.toml" "$HOME/.config/starship.toml" 2>/dev/null || true
    fi

    ok "Developer tools configured"
}

# ──────────────────────────────────────────────
#  Main
# ──────────────────────────────────────────────
main() {
    echo ""
    echo "  ╔══════════════════════════════════════╗"
    echo "  ║   Trimum Ubuntu Desktop Installer    ║"
    echo "  ╚══════════════════════════════════════╝"
    echo ""

    check_preflight
    install_base_packages
    install_flatpak_apps
    apply_gnome_settings

    # Apply default theme (can be overridden by TRIMUM_THEME env)
    apply_theme "${TRIMUM_THEME:-catppuccin}"

    setup_dev_tools

    echo ""
    echo -e "${GREEN}✓ Trimum Ubuntu Desktop installation complete!${NC}"
    echo "  Please log out and back in for all changes to take effect."
    echo ""
}

main "$@"
