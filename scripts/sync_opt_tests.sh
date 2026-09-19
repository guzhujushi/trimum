#!/usr/bin/env bash
set -euo pipefail

# Copy CLI tests from the development checkout to the deployed tree.
# Run this on the remote host with sudo:
#   sudo bash /tmp/sync_opt_tests.sh
SOURCE_DIR="/home/guzhujushi/trimum/tests"
DEST_DIR="/opt/trimum/tests"
FILES=("test_cli.py" "test_cli_commands.py")

install -d -o root -g root -m 0755 "$DEST_DIR"
for file in "${FILES[@]}"; do
    install -o root -g root -m 0644 "$SOURCE_DIR/$file" "$DEST_DIR/$file"
    echo "installed $SOURCE_DIR/$file -> $DEST_DIR/$file"
done