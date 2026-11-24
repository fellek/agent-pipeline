#!/usr/bin/env bash
set -euo pipefail

# Lets this repository's own autopilot run a release: checks out <tag> in the git
# worktree .claude/skills/pipeline, since the repository cannot be its own submodule.
worktree=.claude/skills/pipeline
fail() { echo "use-release: $*" >&2; exit 1; }

[[ $# -eq 1 && -n $1 ]] || fail "usage: use-release.sh <tag>"
tag=refs/tags/$1
[ "$(git rev-parse --show-toplevel)" = "$(pwd -P)" ] || fail "run it in the repository root"
# git's own message tells a missing tag from a network or auth error.
git fetch --quiet origin "+$tag:$tag" || fail "fetching tag $1 from origin failed, see above"

common_dir() { git -C "$1" rev-parse --path-format=absolute --git-common-dir; }

if [ -e "$worktree" ]; then
  # An independent clone there would not see the tag fetched into this repository.
  [ "$(git -C "$worktree" rev-parse --show-toplevel)" = "$(cd "$worktree" && pwd -P)" ] \
    && [ "$(common_dir "$worktree")" = "$(common_dir .)" ] \
    || fail "$worktree is not a worktree of this repository"
  [ -z "$(git -C "$worktree" status --porcelain)" ] || fail "$worktree has changes"
  git -C "$worktree" switch --quiet --detach "$tag"
else
  # Forgets a worktree whose directory was deleted, so it can be added again.
  git worktree prune
  git worktree add --quiet --detach "$worktree" "$tag"
fi
echo "$worktree: $1"
