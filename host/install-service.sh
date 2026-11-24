#!/usr/bin/env bash
set -euo pipefail

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
label=${1:-ready}

[[ $# -le 1 && $label =~ ^[A-Za-z0-9._-]+$ ]] || { echo "invalid label: $*" >&2; exit 1; }

mkdir -p "$unit_dir"
sed "s|autopilot-service.sh ready$|autopilot-service.sh $label|" "$(dirname "$0")/autopilot.service" \
  > "$unit_dir/autopilot.service"
systemctl --user daemon-reload
systemctl --user enable --now autopilot.service
