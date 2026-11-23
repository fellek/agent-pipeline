#!/usr/bin/env bash
set -euo pipefail

tmux kill-session -t autopilot 2>/dev/null || echo "autopilot is not running"
