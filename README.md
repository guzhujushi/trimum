# Trimum — Ubuntu Desktop Edition

> Full desktop experience for Ubuntu 24.04 LTS (Noble).
> Built on GNOME, inspired by Omakub/Omabuntu and Omarchy.

## What's Inside

| Directory | Description |
|-----------|-------------|
| `src/` | Cross-platform Trimum core (same as all editions) |
| `desktop/` | Ubuntu-specific desktop configuration |
| `desktop/install.sh` | One-command installer |
| `desktop/themes/` | 21 GNOME themes with color schemes |
| `desktop/config/` | GNOME settings, kitty, starship |
| `desktop/install/` | Package lists (apt + flatpak) |
| `desktop/scripts/` | Theme switcher, utilities |

## Quick Install

```bash
cd desktop
bash install.sh
```

Or set theme before install:
```bash
TRIMUM_THEME=tokyo-night bash install.sh
```

## Versions

| Edition | Location | Desktop |
|---------|----------|---------|
| Arch Linux | `D:\trimum-arch` | Hyprland + Waybar |
| **Ubuntu** | **`D:\trimum-ubuntu`** | **GNOME + kitty** |
| Server | `D:\trimum-server` | None (headless) |

## Themes

21 themes available. Switch with:
```bash
bash desktop/scripts/theme-switcher.sh    # list themes
bash desktop/scripts/theme-switcher.sh tokyo-night  # apply
```
