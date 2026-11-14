#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."
session=autopilot
channel=plugin:telegram@claude-plugins-official
min_claude=2.1.80
label=${1:-ready}

if tmux has-session -t "$session" 2>/dev/null; then
  exec .github/scripts/autopilot-status.sh
fi

fail() { echo "autopilot: $*, see docs/autopilot.md" >&2; exit 1; }

[ $# -le 1 ] && [[ $label =~ ^[^[:space:]]+$ ]] || fail "label must not contain whitespace"

for cmd in claude git gh tmux bun uv; do
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
# CLAUDE_CODE_EFFORT_LEVEL would override the effort set per skill.
tmux new-session -d -s "$session" -c "$PWD" env -u CLAUDE_CODE_EFFORT_LEVEL \
  claude --model sonnet --effort medium --channels "$channel" -- "/autopilot $label"
