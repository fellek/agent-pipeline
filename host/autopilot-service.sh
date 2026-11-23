#!/usr/bin/env bash
set -euo pipefail

"$(dirname "$0")/autopilot-start.sh" "$@"
while tmux has-session -t autopilot 2>/dev/null; do
  sleep 10
done
echo "autopilot: tmux session ended" >&2
exit 1
