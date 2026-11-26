#!/usr/bin/env bash
set -euo pipefail

session=$("$(dirname "$0")/autopilot-name.sh")
# As ExecStop=, end autopilot-service.sh first: seeing the session gone, it would
# exit 1 and fail the unit. systemd takes its SIGTERM as a clean stop.
[ -z "${MAINPID:-}" ] || kill "$MAINPID" 2>/dev/null || true
tmux kill-session -t "=$session" 2>/dev/null || echo "$session is not running"
