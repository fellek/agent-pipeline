#!/usr/bin/env bash
set -euo pipefail

host=$(cd "$(dirname "$0")" && pwd)
session=$("$host/autopilot-name.sh")
channel=plugin:telegram@claude-plugins-official
min_claude=2.1.239
label=${1:-ready}

fail() { echo "$session: $*, see ${host%/host}/docs/autopilot.md" >&2; exit 1; }

reason=$("$host/require-project-root.sh") || fail "$reason"

if tmux has-session -t "=$session" 2>/dev/null; then
  exec "$host/autopilot-status.sh"
fi

# Versions with one instance per host named the session "autopilot".
! tmux has-session -t "=autopilot" 2>/dev/null \
  || fail "the old session autopilot is running, replace it with install-service.sh"

[ $# -le 1 ] && [[ $label =~ ^[^[:space:]]+$ ]] || fail "label must not contain whitespace"

for cmd in claude git gh tmux bun; do
  command -v "$cmd" >/dev/null || fail "$cmd is missing"
done
claude_version=$(claude --version | cut -d' ' -f1)
[ "$(printf '%s\n' "$min_claude" "$claude_version" | sort -V | head -1)" = "$min_claude" ] \
  || fail "claude $claude_version is older than $min_claude"
gh auth status >/dev/null 2>&1 || fail "gh is not logged in"
claude plugin list | grep -q telegram || fail "Telegram plugin is not installed"
[ -n "${TELEGRAM_BOT_TOKEN:-}" ] || [ -f "$HOME/.claude/channels/telegram/.env" ] \
  || fail "Telegram token is missing"
[ "$(loginctl show-user "$(id -un)" -p Linger --value)" = yes ] || fail "linger is not enabled"

mkdir -p .pipeline
status_line='{"statusLine":{"type":"command","command":"'"$host"'/autopilot-statusline.py","refreshInterval":60}}'
# CLAUDE_CODE_EFFORT_LEVEL would override the effort set per skill.
# The retry watchdog waits out session and weekly limits instead of opening the limit menu.
tmux new-session -d -s "$session" -c "$PWD" env -u CLAUDE_CODE_EFFORT_LEVEL CLAUDE_CODE_RETRY_WATCHDOG=1 \
  claude --settings "$status_line" --model sonnet --effort medium --channels "$channel" -- "/pipeline:autopilot $label"
