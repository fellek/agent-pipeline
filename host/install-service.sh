#!/usr/bin/env bash
set -euo pipefail

# Installs the autopilot of the project in the working directory as a user service.
host=$(cd "$(dirname "$0")" && pwd)
unit=$("$host/autopilot-name.sh")
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
label=${1:-ready}

[[ $# -le 1 && $label =~ ^[A-Za-z0-9._-]+$ ]] || { echo "invalid label: $*" >&2; exit 1; }
# Keeps the paths free of systemd specifiers, quoting and sed delimiters.
for path in "$PWD" "$host"; do
  [[ $path =~ ^[A-Za-z0-9._/-]+$ ]] || { echo "unsupported path: $path" >&2; exit 1; }
done

mkdir -p "$unit_dir"
sed -e "s|@NAME@|$unit|" -e "s|@PROJECT@|$PWD|" -e "s|@HOST@|$host|" -e "s|@LABEL@|$label|" \
  "$host/autopilot.service" > "$unit_dir/$unit.service"
systemctl --user daemon-reload
systemctl --user enable --now "$unit.service"
