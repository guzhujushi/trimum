#!/bin/bash
# Trimum Ubuntu — Generate remaining theme colors.conf files
# Run from desktop/ directory

THEMES_DIR="$(dirname "$0")/../themes"

# Theme definitions: name|variant|bg|surface|overlay|subtext|text|accent|red|green|yellow|blue|pink
themes=(
    "everforest|dark|#2b3339|#2d3c46|#545c5e|#859289|#d3c6aa|#a7c080|#e67e80|#83c092|#dbbc7f|#7fbbb3|#d699b6"
    "kanagawa|dark|#1f1f28|#2a2a37|#54546d|#72728a|#dcd7ba|#7fb4ca|#c34043|#76946a|#c0a36e|#7e9cd8|#938aa9"
    "vantablack|dark|#000000|#0a0a0a|#1a1a1a|#555555|#cccccc|#00ffaa|#ff3355|#00cc88|#ffaa33|#33aaff|#ff33aa"
    "white|light|#ffffff|#f5f5f5|#e0e0e0|#999999|#333333|#6366f1|#ef4444|#22c55e|#eab308|#3b82f6|#ec4899"
    "hackerman|dark|#0c0c0c|#141414|#282828|#558855|#33ff33|#00ff00|#ff0033|#00ff00|#ffff00|#0066ff|#ff00ff"
    "ethereal|dark|#0f0e17|#1a1932|#3e3b6b|#8882c4|#fffffe|#e53170|#ff0033|#00cc99|#ffcc00|#0077ff|#ff66cc"
    "lumon|dark|#0a0a0f|#14142b|#2a2a5e|#6e6eb3|#e2e2ff|#8888ff|#ff3355|#44ff88|#ffaa33|#4488ff|#ff66aa"
    "matte-black|dark|#1a1a1a|#222222|#2e2e2e|#5e5e5e|#b4b4b4|#b4b4b4|#b4b4b4|#b4b4b4|#b4b4b4|#b4b4b4|#b4b4b4"
    "miasma|dark|#0f0f12|#1a1a22|#2d2d3e|#5e5e7e|#b8b8d0|#9b72cf|#e06070|#78c0a0|#d4b060|#6888d0|#ce88b0"
    "osaka-jade|dark|#0d1117|#161b22|#30363d|#6e7681|#e6edf3|#58a6ff|#ff7b72|#3fb950|#d29922|#58a6ff|#bc8cff"
    "retro-82|dark|#1a1a2e|#16213e|#0f3460|#6e85b7|#e8e8e8|#e94560|#ff3366|#00ff88|#ffcc00|#3399ff|#ff66aa"
    "ristretto|dark|#2b2b2b|#383838|#505050|#808080|#d4d4d4|#c4a46c|#cc6d6d|#8caa6d|#d4b46c|#6d8caa|#aa6d8c"
    "solitude|dark|#1e2129|#262a35|#3a4050|#767f99|#cbd0df|#8496c4|#c46a6a|#8ab08a|#c4b06a|#6a8ab0|#b06a8a"
    "flexoki-light|light|#fffcf0|#f2f0e5|#b7b5ac|#6f6e69|#100f0f|#b3603a|#b3453a|#879a55|#d6a04a|#4385be|#b34572"
)

for t in "${themes[@]}"; do
    IFS='|' read -r name variant bg surface overlay subtext text accent red green yellow blue pink <<< "$t"
    dir="$THEMES_DIR/$name"
    mkdir -p "$dir/backgrounds"
    cat > "$dir/colors.conf" << EOF
# ${name^} — Trimum Ubuntu Theme
export TRIMUM_THEME_NAME="${name^}"
export TRIMUM_THEME_VARIANT="$variant"
export TRIMUM_BG="$bg"
export TRIMUM_SURFACE="$surface"
export TRIMUM_OVERLAY="$overlay"
export TRIMUM_SUBTEXT="$subtext"
export TRIMUM_TEXT="$text"
export TRIMUM_ACCENT="$accent"
export TRIMUM_RED="$red"
export TRIMUM_GREEN="$green"
export TRIMUM_YELLOW="$yellow"
export TRIMUM_BLUE="$blue"
export TRIMUM_PINK="$pink"
export TRIMUM_GTK_THEME="$name"
export TRIMUM_ICON_THEME="$name"
export TRIMUM_CURSOR_THEME="Yaru"
export TRIMUM_TERMINAL_THEME="${name^}"
export TRIMUM_WALLPAPER="themes/$name/backgrounds/default.jpg"
EOF
    echo "  ✓ $name"
done

echo "Done. Generated ${#themes[@]} themes."
