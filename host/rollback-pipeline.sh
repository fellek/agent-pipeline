#!/usr/bin/env bash
set -euo pipefail

# Opens the pull request that moves the project in the working directory back to the
# release its default branch pinned before the current one (bump.sh).
host=$(cd "$(dirname "$0")" && pwd)
sub=.claude/skills/pipeline
pin=.claude/pipeline-release
fail() { echo "rollback-pipeline: $*" >&2; exit 1; }

[ $# -eq 0 ] || fail "usage: rollback-pipeline.sh"
reason=$("$host/require-project-root.sh") || fail "$reason"
default=$("$host/../bin/default-branch.py")
git fetch --quiet origin "$default"
if [ "$(git ls-tree "origin/$default" -- "$sub" | cut -d' ' -f1)" = 160000 ]; then
  git -C "$sub" fetch --quiet --tags origin || fail "fetching the tags of the pipeline failed, see above"
  pinned() { git rev-parse --verify --quiet "$1:$sub"; }
  name() { git -C "$sub" describe --tags --exact-match "$1" 2>/dev/null || fail "the earlier pin $1 is no release"; }
  target=$sub
else
  pinned() { git show "$1:$pin" 2>/dev/null | tr -d '[:space:]'; }
  name() { echo "$1"; }
  target=$pin
fi

current=$(pinned "origin/$default") || fail "$target is not on $default"
for commit in $(git rev-list "origin/$default" -- "$target"); do
  previous=$(pinned "$commit") || continue
  if [ -n "$previous" ] && [ "$previous" != "$current" ]; then
    tag=$(name "$previous") || exit 1
    exec "$host/bump.sh" "$tag"
  fi
done
fail "$default pinned no release before the current one"
