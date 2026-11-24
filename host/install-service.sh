#!/usr/bin/env bash
set -euo pipefail

# Installs the autopilot of the project in the working directory as a user service.
# Replaces the unit and tmux session "autopilot" of versions with one instance per host.
host=$(cd "$(dirname "$0")" && pwd)
unit=$("$host/autopilot-name.sh")
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
old_unit="$unit_dir/autopilot.service"
label=${1:-ready}
fail() { echo "$*" >&2; exit 1; }

[[ $# -le 1 && $label =~ ^[A-Za-z0-9._-]+$ ]] || fail "invalid label: $*"
[ "$(git rev-parse --show-toplevel 2>/dev/null)" = "$(pwd -P)" ] \
  || fail "run it in the project root"
# Keeps the paths free of systemd specifiers, quoting and sed delimiters.
for path in "$PWD" "$host"; do
  [[ $path =~ ^[A-Za-z0-9._/-]+$ ]] || fail "unsupported path: $path"
done

if [ -f "$old_unit" ]; then
  old_project=$(sed -n 's/^WorkingDirectory=//p' "$old_unit")
  old_project=${old_project//%h/$HOME}
  [ "$old_project" = "$PWD" ] || fail "$old_unit runs $old_project, not $PWD: remove it first"
  systemctl --user disable --now autopilot.service
  rm "$old_unit"
  tmux kill-session -t "=autopilot" 2>/dev/null || true
  echo "replaced autopilot.service with $unit.service"
fi

mkdir -p "$unit_dir"
sed -e "s|@NAME@|$unit|" -e "s|@PROJECT@|$PWD|" -e "s|@HOST@|$host|" -e "s|@LABEL@|$label|" \
  "$host/autopilot.service" > "$unit_dir/$unit.service"
systemctl --user daemon-reload
systemctl --user enable --now "$unit.service"
