#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

mkdir -p "$unit_dir"
cp deploy/autopilot.service "$unit_dir/"
systemctl --user daemon-reload
systemctl --user enable --now autopilot.service
