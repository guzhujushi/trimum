#!/bin/bash
# Trimum Ubuntu — Theme Switcher
# Usage: bash scripts/theme-switcher.sh [theme-name]
#        Lists available themes if no argument given.

TRIMUM_DESKTOP="$(cd "$(dirname "$0")/.." && pwd)"
THEMES_DIR="$TRIMUM_DESKTOP/themes"

# List themes if no argument
if [ $# -eq 0 ]; then
    echo "Available themes:"
    echo ""
    for theme in "$THEMES_DIR"/*/; do
        name=$(basename "$theme")
        if [ -f "$theme/colors.conf" ]; then
            variant=$(grep "TRIMUM_THEME_VARIANT" "$theme/colors.conf" 2>/dev/null | cut -d= -f2 | tr -d '"')
            echo "  $name ($variant)"
        fi
    done
    echo ""
    echo "Usage: bash $0 <theme-name>"
    exit 0
fi

THEME="$1"
THEME_DIR="$THEMES_DIR/$THEME"

if [ ! -d "$THEME_DIR" ]; then
    echo "Error: Theme '$THEME' not found in $THEMES_DIR"
    echo "Run without arguments to list available themes."
    exit 1
fi

if [ ! -f "$THEME_DIR/colors.conf" ]; then
    echo "Error: Theme '$THEME' has no colors.conf"
    exit 1
fi

echo "Applying theme: $THEME..."
source "$THEME_DIR/colors.conf"

# Apply GNOME Shell theme
if command -v gsettings &>/dev/null; then
    if [ -n "$TRIMUM_GTK_THEME" ] && [ "$TRIMUM_GTK_THEME" != "" ]; then
        gsettings set org.gnome.desktop.interface gtk-theme "$TRIMUM_GTK_THEME" 2>/dev/null || true
        gsettings set org.gnome.desktop.interface icon-theme "$TRIMUM_ICON_THEME" 2>/dev/null || true
    fi
    
    # Apply accent color if GNOME 45+
    if [ -n "$TRIMUM_ACCENT" ]; then
        gsettings set org.gnome.desktop.interface accent-color "$TRIMUM_ACCENT" 2>/dev/null || true
    fi
fi

echo "✓ Theme '$THEME' applied."
echo "  Accent: $TRIMUM_ACCENT"
echo "  GTK:    $TRIMUM_GTK_THEME"
echo "  Icons:  $TRIMUM_ICON_THEME"
