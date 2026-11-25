#!/usr/bin/env bash
set -euo pipefail

# Opens the pull request that moves the project in the working directory to the
# release before the one its default branch pins (bump.sh), in release order.
host=$(cd "$(dirname "$0")" && pwd)
sub=.claude/skills/pipeline
pin=.claude/pipeline-release
fail() { echo "rollback-pipeline: $*" >&2; exit 1; }

[ $# -eq 0 ] || fail "usage: rollback-pipeline.sh"
reason=$("$host/require-project-root.sh") || fail "$reason"
url=$(sed -n 's/^ *"repository": *"\([^"]*\)".*/\1/p' "$host/../.claude-plugin/plugin.json")
url=${url%/}
repo=${url#https://github.com/}
default=$("$host/../bin/default-branch.py")
git fetch --quiet origin "$default"
if [ "$(git ls-tree "origin/$default" -- "$sub" | cut -d' ' -f1)" = 160000 ]; then
  git -C "$sub" fetch --quiet --tags origin || fail "fetching the tags of the pipeline failed, see above"
  current=$(git -C "$sub" describe --tags --exact-match "$(git rev-parse "origin/$default:$sub")" 2>/dev/null) \
    || fail "$sub on $default is on no release"
else
  current=$(git show "origin/$default:$pin" 2>/dev/null | tr -d '[:space:]')
  [ -n "$current" ] || fail "$pin is not on $default"
fi
# Newest first, so the release after the current one in the list is the one before it.
previous=$(gh release list --repo "$repo" --exclude-drafts --limit 100 --json tagName --jq '.[].tagName' \
  | sed -n "/^${current//./\\.}\$/{n;p;q}") || fail "listing the releases of $repo failed"
[ -n "$previous" ] || fail "no release before $current"
exec "$host/bump.sh" "$previous"
