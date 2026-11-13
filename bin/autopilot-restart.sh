#!/usr/bin/env bash
set -euo pipefail

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
systemctl --user is-active --quiet autopilot
exec "$(dirname "$0")/autopilot-stop.sh"
