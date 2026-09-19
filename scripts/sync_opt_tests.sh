#!/usr/bin/env bash
set -euo pipefail

# Copy CLI tests from the development checkout to the deployed tree.
# Run this on the remote host with sudo:
#   sudo bash /tmp/sync_opt_tests.sh
SOURCE="${SOURCE:-/home/guzhujushi/trimum/tests/test_cli.py}"
DEST_DIR="/opt/trimum/tests"

install -d -o root -g root -m 0755 "$DEST_DIR"
install -o root -g root -m 0644 "$SOURCE" "$DEST_DIR/test_cli.py"
echo "installed $SOURCE -> $DEST_DIR/test_cli.py"