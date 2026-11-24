#!/usr/bin/env bash
set -euo pipefail

host=$(dirname "$0")
# State is read from .pipeline/ of the project root.
reason=$("$host/require-project-root.sh") || { echo "autopilot-status: $reason" >&2; exit 1; }
session=$("$host/autopilot-name.sh")
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

running=false
tmux has-session -t "=$session" 2>/dev/null && running=true
echo "tmux running: $running"
echo "service: $(systemctl --user is-active "$session.service" 2>/dev/null || true)"

echo "--- .pipeline/state.json"
cat .pipeline/state.json 2>/dev/null || echo "(none)"
echo "--- limit"
cat .pipeline/limit.json 2>/dev/null || echo "(none)"
echo "--- .pipeline/autopilot.log"
tail -n 20 .pipeline/autopilot.log 2>/dev/null || echo "(none)"

if $running; then
  echo "--- screen"
  tmux capture-pane -p -t "=$session:" | grep -v '^$' | tail -n 15
fi
