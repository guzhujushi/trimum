# ai() shell function for trimum
# Usage: ai "check disk space"
#        cat log | ai "explain error"

# trimum 环境：定位项目根目录，并把 scripts/ 加入 PATH（供 trimum-theme 等使用）
export TRIMUM_HOME="${TRIMUM_HOME:-/opt/trimum}"
export PATH="$TRIMUM_HOME/scripts:$PATH"

ai() {
    if [ -p /dev/stdin ]; then
        # Pipe mode: read stdin, pass as context
        local input
        input=$(cat)
        echo "$input" | trm "$*"
    else
        trm "$*"
    fi
}
