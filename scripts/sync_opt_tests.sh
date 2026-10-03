#!/usr/bin/env bash
set -euo pipefail

# Copy the development checkout into the deployed tree (root-owned paths).
# Run this on the remote host with sudo:
#   sudo bash /tmp/sync_opt_tests.sh
SOURCE_DIR="/home/guzhujushi/trimum/tests"
DEST_DIR="/opt/trimum/tests"
SCRIPT_DIR="/home/guzhujushi/trimum/scripts"
DEST_SCRIPT_DIR="/opt/trimum/scripts"

install -d -o root -g root -m 0755 "$DEST_SCRIPT_DIR"
for script in sync_opt_tests.sh restart_trmd.sh; do
    install -o root -g root -m 0755 "$SCRIPT_DIR/$script" "$DEST_SCRIPT_DIR/$script"
    echo "installed $SCRIPT_DIR/$script -> $DEST_SCRIPT_DIR/$script"
done

# 子 Agent 模板（AgentManager 会从 agents 目录拉起）
install -d -o root -g root -m 0755 "$DEST_SCRIPT_DIR/agent-template"
install -o root -g root -m 0644 "$SCRIPT_DIR/agent-template/main.py" "$DEST_SCRIPT_DIR/agent-template/main.py"
echo "installed $SCRIPT_DIR/agent-template/main.py -> $DEST_SCRIPT_DIR/agent-template/main.py"

# 全量测试文件（/opt/trimum/tests 为 root:root，普通用户写不进）
install -d -o root -g root -m 0755 "$DEST_DIR"
for file in "$SOURCE_DIR"/*.py; do
    install -o root -g root -m 0644 "$file" "$DEST_DIR/$(basename "$file")"
done
echo "installed $(ls -1 "$SOURCE_DIR"/*.py | wc -l) test files -> $DEST_DIR"
