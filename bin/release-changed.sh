#!/usr/bin/env bash
set -euo pipefail

# Tells the autopilot whether the default branch of the project pins another pipeline
# release than the one its session runs. The session loads the release only at start,
# and in a project git pull moves the submodule, so `record` notes the running commit
# at start; without an argument the script prints the name of the newly pinned release,
# or nothing if the pin is unchanged.
#
# Usage:
#   release-changed.sh record
#   release-changed.sh
bin=$(cd "$(dirname "$0")" && pwd)
sub=.claude/skills/pipeline
pin=.claude/pipeline-release
running=.pipeline/release
fail() { echo "release-changed: $*" >&2; exit 1; }

if [ "${1-}" = record ] && [ $# -eq 1 ]; then
  mkdir -p .pipeline
  git -C "$bin/.." rev-parse HEAD >"$running"
  exit
fi
[ $# -eq 0 ] || fail "usage: release-changed.sh [record]"
[ -f "$running" ] || fail "$running is missing, run release-changed.sh record at start"

default=$("$bin/default-branch.py")
git fetch --quiet origin "$default"
if [ "$(git ls-tree "origin/$default" -- "$sub" | cut -d' ' -f1)" = 160000 ]; then
  pinned=$(git rev-parse "origin/$default:$sub")
  [ "$pinned" != "$(cat "$running")" ] || exit 0
  git -C "$sub" fetch --quiet --tags origin || true
  git -C "$sub" describe --tags --exact-match "$pinned" 2>/dev/null || echo "${pinned:0:12}"
else
  name=$(git show "origin/$default:$pin" 2>/dev/null | tr -d '[:space:]') \
    || fail "origin/$default pins no release: neither a submodule $sub nor $pin"
  git fetch --quiet origin "+refs/tags/$name:refs/tags/$name" \
    || fail "fetching tag $name of $pin failed, see above"
  [ "$(git rev-parse "refs/tags/$name^{commit}")" != "$(cat "$running")" ] || exit 0
  echo "$name"
fi
