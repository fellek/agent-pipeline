#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

if tmux has-session -t autopilot 2>/dev/null; then
  echo "tmux: running"
else
  echo "tmux: stopped"
fi
echo "service: $(systemctl --user is-active autopilot.service 2>/dev/null || true)"

echo "--- .pipeline/state.json"
cat .pipeline/state.json 2>/dev/null || echo "(none)"
echo "--- .pipeline/autopilot.log"
tail -n 20 .pipeline/autopilot.log 2>/dev/null || echo "(none)"

if tmux has-session -t autopilot 2>/dev/null; then
  echo "--- screen"
  tmux capture-pane -p -t autopilot | grep -v '^$' | tail -n 15
fi
