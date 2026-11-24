#!/usr/bin/env bash
set -euo pipefail

host="$(dirname "$0")/../host"
unit=$("$host/autopilot-name.sh")
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
systemctl --user is-active --quiet "$unit"
systemctl --user reset-failed "$unit"
exec "$host/autopilot-stop.sh"
