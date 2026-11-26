#!/usr/bin/env bash
set -euo pipefail

# Sets up the gate of the host (host/gate.py) for the autopilot of Linux user <user>
# on GitHub repository <owner/repo>, as root. Reads the GitHub token of the project
# from stdin; an empty one keeps the stored token. update-host runs it for each
# release; it also installs update-host and its timer pipeline-update@<user>.
host=$(cd "$(dirname "$0")" && pwd)
plugin=${host%/host}
# Prefix of the system paths, for the tests only.
root=${GATE_ROOT:-}
gate_user=pipeline-gate
fail() { echo "install-gate: $*" >&2; exit 1; }

[ $# -eq 2 ] || fail "usage: install-gate.sh <user> <owner/repo> < token"
user=$1
repo=$2
[ -n "$root" ] || [ "$(id -u)" = 0 ] || fail "run as root"
[[ $repo =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || fail "invalid repository: $repo"
entry=$(getent passwd "$user") || fail "no user $user"
home=$(cut -d: -f6 <<<"$entry")
[ "$user" != "$gate_user" ] && [ "$user" != root ] || fail "the autopilot must not run as $user"

getent passwd "$gate_user" >/dev/null \
  || useradd --system --create-home --home-dir /var/lib/pipeline-gate --shell /usr/sbin/nologin "$gate_user"

dir() { mkdir -p "$1"; chmod "$2" "$1"; chown "$3" "$1"; }
file() { chmod "$2" "$1"; chown "$3" "$1"; }

# Root owns the code, so neither the autopilot nor the gate user can change it.
dir "$root/opt/pipeline" 0755 root:root
# A new file, not one written over: update-host runs this script while bash reads it.
for name in gate update-host; do
  source=$host/gate.py
  [ "$name" = gate ] || source=$host/update-host.sh
  cp "$source" "$root/opt/pipeline/$name.tmp"
  file "$root/opt/pipeline/$name.tmp" 0755 root:root
  mv "$root/opt/pipeline/$name.tmp" "$root/opt/pipeline/$name"
done
sed -n 's|^ *"repository": *"https://github.com/\([^"]*\)".*|\1|p' "$plugin/.claude-plugin/plugin.json" \
  >"$root/opt/pipeline/pipeline-repo"
file "$root/opt/pipeline/pipeline-repo" 0644 root:root
for source in "$plugin/bin/attestation.py" "$plugin/bin/trust.py" "$host/gate-review.md" "$plugin/rules/workflow.md"; do
  cp "$source" "$root/opt/pipeline/"
  file "$root/opt/pipeline/$(basename "$source")" 0644 root:root
done

store=$root/etc/pipeline-gate/projects/$user
dir "$root/etc/pipeline-gate" 0700 "$gate_user:$gate_user"
dir "$root/etc/pipeline-gate/projects" 0700 "$gate_user:$gate_user"
dir "$store" 0700 "$gate_user:$gate_user"
dir "$root/var/lib/pipeline-gate/projects" 0700 "$gate_user:$gate_user"
(
  umask 077
  printf '%s\n' "$repo" >"$store/repo"
  IFS= read -r token || true
  if [ -n "$token" ]; then
    printf '%s\n' "$token" >"$store/token"
  fi
  [ -s "$store/token" ] || fail "no token on stdin and none stored"
  [ -s "$store/review-key" ] || python3 -c 'import secrets; print(secrets.token_hex(32))' >"$store/review-key"
)
for name in repo token review-key; do
  file "$store/$name" 0600 "$gate_user:$gate_user"
done

mkdir -p "$root/etc/sudoers.d"
sudoers=$root/etc/sudoers.d/pipeline-gate-$user
printf '%s ALL=(%s) NOPASSWD: /opt/pipeline/gate\n' "$user" "$gate_user" >"$sudoers.tmp"
visudo -cf "$sudoers.tmp" >/dev/null || fail "visudo rejects $sudoers"
file "$sudoers.tmp" 0440 root:root
mv "$sudoers.tmp" "$sudoers"

# gh and git of the autopilot reach GitHub only through the gate.
dir "$home/.local/bin" 0755 "$user:"
cp "$host/gh-shim.py" "$home/.local/bin/gh"
file "$home/.local/bin/gh" 0755 "$user:"
transport='ext::sudo -n -u pipeline-gate /opt/pipeline/gate %S'
config=$home/.gitconfig
touch "$config"
git config --file "$config" --unset-all "url.$transport.insteadOf" || true
git config --file "$config" --add "url.$transport.insteadOf" "https://github.com/$repo"
git config --file "$config" --add "url.$transport.insteadOf" "https://github.com/$repo.git"
git config --file "$config" protocol.ext.allow always
file "$config" 0644 "$user:"

# The timer updates the pipeline of the user without the maintainer.
units=$root/etc/systemd/system
mkdir -p "$units"
cp "$host/pipeline-update@.service" "$host/pipeline-update@.timer" "$units/"
systemctl daemon-reload
systemctl enable --quiet --now "pipeline-update@$user.timer"

cat <<EOF
Gate set up for $user on $repo.
- Log in Claude Code for the reviews once: sudo -u $gate_user -H claude, then /login.
- Set the Actions secret PIPELINE_REVIEW_KEY of $repo to the key in /etc/pipeline-gate/projects/$user/review-key.
- $user must hold no GitHub token of its own: remove ~/.config/gh/hosts.yml and git credentials of $user.
EOF
