# ai() shell function for trimum
# Usage: ai "check disk space"
#        cat log | ai "explain error"
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