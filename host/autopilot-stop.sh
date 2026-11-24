#!/usr/bin/env bash
set -euo pipefail

session=$("$(dirname "$0")/autopilot-name.sh")
tmux kill-session -t "=$session" 2>/dev/null || echo "$session is not running"
