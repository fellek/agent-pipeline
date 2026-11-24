#!/usr/bin/env bash
set -euo pipefail

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
systemctl --user is-active --quiet autopilot
systemctl --user reset-failed autopilot
exec "$(dirname "$0")/../host/autopilot-stop.sh"
