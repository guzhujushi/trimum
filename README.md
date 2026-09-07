# Trimum — Server Edition

> Cross-platform server deployment of the Trimum multi-agent system.
> No desktop/GUI dependencies. Pure Python + config.

## Scope

This edition contains only the cross-platform core (`src/trimum_core`),
tests, config, and documentation. No Hyprland/Waybar/Kitty/Alacritty
desktop configuration, no wallpapers, no Arch Linux specific scripts.

## Versions

| Edition | Location | Platform | Desktop |
|---------|----------|----------|---------|
| Arch Linux | `D:\trimum-arch` | Arch Linux | Hyprland + full dotfiles |
| Server | `D:\trimum-server` | Ubuntu / Any Linux | None (headless) |
| *(future)* macOS | — | macOS | — |

## Quick Start

```bash
pip install -e src/trimum_core
trimum --config config/trimum.yaml
```

See `docs/` for architecture and deployment documentation.
