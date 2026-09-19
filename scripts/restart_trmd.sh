#!/usr/bin/env bash
# ???? trimum daemon???/????
#
#   bash scripts/restart_trmd.sh
#
# ???
# - ?????????????????? shutdown ?? unlink socket ???
#   ???????? bind ?? socket ?????
# - pkill ? pattern ????????? shell ???????
set -uo pipefail

PATTERN='trimum_core[.]main'
PYTHON="${TRIMUM_PYTHON:-/opt/trimum/venv/bin/python}"
WORKDIR="${TRIMUM_WORKDIR:-/opt/trimum}"
LOGFILE="${TRIMUM_DAEMON_LOG:-/tmp/trmd.out}"

OLD=$(pgrep -f "$PATTERN" | head -1)
if [ -n "${OLD:-}" ]; then
    echo "stopping old daemon $OLD"
    kill -TERM "$OLD"
    for i in $(seq 1 20); do
        sleep 1
        kill -0 "$OLD" 2>/dev/null || { echo "old exited after ${i}s"; break; }
    done
    if kill -0 "$OLD" 2>/dev/null; then
        echo "old still alive, sending SIGKILL"
        kill -9 "$OLD"
        sleep 1
    fi
fi

cd "$WORKDIR"
setsid nohup "$PYTHON" -m trimum_core.main > "$LOGFILE" 2>&1 < /dev/null &
sleep 5

echo "--- process ---"
pgrep -af "$PATTERN" || echo "(daemon not running)"
echo "--- daemon status ---"
trm daemon status 2>&1 | tail -2
echo "--- log tail ($LOGFILE) ---"
tail -4 "$LOGFILE"
