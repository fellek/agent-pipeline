#!/usr/bin/env bash
set -euo pipefail

# Lets this repository's own autopilot run a release: checks out <tag> in the git
# worktree .claude/skills/pipeline, since the repository cannot be its own submodule.
worktree=.claude/skills/pipeline
fail() { echo "use-release: $*" >&2; exit 1; }

[[ $# -eq 1 && -n $1 ]] || fail "usage: use-release.sh <tag>"
tag=refs/tags/$1
[ "$(git rev-parse --show-toplevel)" = "$(pwd -P)" ] || fail "run it in the repository root"
git fetch --quiet origin "+$tag:$tag" || fail "no tag $1 on origin"

if [ -e "$worktree" ]; then
  [ "$(git -C "$worktree" rev-parse --show-toplevel)" = "$(cd "$worktree" && pwd -P)" ] \
    || fail "$worktree is not a worktree"
  [ -z "$(git -C "$worktree" status --porcelain)" ] || fail "$worktree has changes"
  git -C "$worktree" switch --quiet --detach "$tag"
else
  git worktree add --quiet --detach "$worktree" "$tag"
fi
echo "$worktree: $1"
