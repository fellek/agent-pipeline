#!/usr/bin/env bash
set -euo pipefail

host=$(cd "$(dirname "$0")" && pwd)
session=$("$host/autopilot-name.sh")
plugin=telegram@claude-plugins-official
channel=plugin:$plugin
. "$host/versions.sh"
label=${1:-ready}

fail() { echo "$session: $*, see ${host%/host}/INSTALL.md" >&2; exit 1; }
# A release that bumps a version stops the service; the maintainer learns it here.
fail_with_message() {
  printf '%s\n' "$session: $*" | "${host%/host}/bin/telegram-send.py" >/dev/null 2>&1 || true
  fail "$@"
}

reason=$("$host/require-project-root.sh") || fail "$reason"

if tmux has-session -t "=$session" 2>/dev/null; then
  # The name comes from the repository name alone, so a fork and its upstream clash.
  path=$(tmux display-message -p -t "=$session" '#{session_path}')
  [ "$(cd "$path" 2>/dev/null && pwd -P)" = "$(pwd -P)" ] \
    || fail "session $session runs $path, not $PWD: projects with the same repository name cannot run side by side"
  exec "$host/autopilot-status.sh"
fi

# Versions with one instance per host named the session "autopilot".
! tmux has-session -t "=autopilot" 2>/dev/null \
  || fail "the old session autopilot is running, replace it with install-service.sh"

[ $# -le 1 ] && [[ $label =~ ^[^[:space:]]+$ ]] || fail "label must not contain whitespace"

# bwrap and socat run the Bash sandbox of .claude/settings.json.
for cmd in claude git gh sudo tmux bun python3 bwrap socat; do
  command -v "$cmd" >/dev/null || fail "$cmd is missing"
done
claude_version=$(claude --version | cut -d' ' -f1)
[ "$claude_version" = "$claude_code" ] \
  || fail_with_message "claude $claude_version is not $claude_code, run: claude install $claude_code"
# Only the gate may hold a GitHub token, see install-gate.sh.
! grep -qs oauth_token "$HOME/.config/gh/hosts.yml" && [ -z "${GH_TOKEN:-}${GITHUB_TOKEN:-}" ] \
  || fail "$(id -un) holds a GitHub token of its own, only the gate may hold it"
"${host%/host}/bin/gate" check >/dev/null 2>&1 || fail "the gate does not reach the repository, see install-gate.sh"
default=$("${host%/host}/bin/default-branch.py") || fail "the default branch is unknown"
warning=$("$host/check-ruleset.py" "$default" 2>&1) || fail "$warning"
# The gate runs as root installed it, so a new release does not reach it by itself.
installed=${PIPELINE_GATE:-/opt/pipeline/gate}
cmp -s "$host/gate.py" "$installed" \
  || warning="${warning:+$warning }Warning: $installed differs from host/gate.py of this release, run install-gate.sh again."
if [ -n "$warning" ]; then
  echo "$session: $warning" >&2
  printf '%s\n' "$warning" | "${host%/host}/bin/telegram-send.py" || true
fi
plugin_version=$(claude plugin list --json | python3 -c '
import json, sys
print(next((p["version"] for p in json.load(sys.stdin) if p["id"] == sys.argv[1]), ""))
' "$plugin" 2>/dev/null) || fail "claude plugin list --json failed"
[ -n "$plugin_version" ] || fail "Telegram plugin is not installed"
[ "$plugin_version" = "$telegram_plugin" ] \
  || fail_with_message "Telegram plugin $plugin_version is not $telegram_plugin"
[ -n "${TELEGRAM_BOT_TOKEN:-}" ] || [ -f "$HOME/.claude/channels/telegram/.env" ] \
  || fail "Telegram token is missing"
# A broken release would otherwise end in a restart loop that only the journal shows.
release=$("$host/check-release.sh" 2>&1) || fail_with_message "$release"
validate=$(claude plugin validate "${host%/host}" 2>&1) \
  || fail_with_message "the pipeline release fails claude plugin validate: $(tail -n 1 <<<"$validate")"
[ "$(loginctl show-user "$(id -un)" -p Linger --value)" = yes ] || fail "linger is not enabled"

mkdir -p .pipeline
status_line='{"statusLine":{"type":"command","command":"'"$host"'/autopilot-statusline.py","refreshInterval":60}}'
# CLAUDE_CODE_EFFORT_LEVEL would override the effort set per skill.
# The retry watchdog waits out session and weekly limits instead of opening the limit menu.
# Without the auto updater the session keeps the version checked above.
# CI and review syncs run in the background; the timeouts only stop a foreground
# command after 10 minutes instead of 2, with up to an hour when a call asks for it.
tmux new-session -d -s "$session" -c "$PWD" env -u CLAUDE_CODE_EFFORT_LEVEL CLAUDE_CODE_RETRY_WATCHDOG=1 \
  DISABLE_AUTOUPDATER=1 \
  BASH_DEFAULT_TIMEOUT_MS=600000 BASH_MAX_TIMEOUT_MS=3600000 \
  claude --settings "$status_line" --model sonnet --effort medium --channels "$channel" -- "/pipeline:autopilot $label"
