#!/usr/bin/env bash
set -euo pipefail

host=$(dirname "$0")
session=$("$host/autopilot-name.sh")
"$host/autopilot-start.sh" "$@"
while tmux has-session -t "=$session" 2>/dev/null; do
  sleep 10
done
echo "$session: tmux session ended" >&2
exit 1
