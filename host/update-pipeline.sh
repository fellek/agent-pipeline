#!/usr/bin/env bash
set -euo pipefail

# Opens the pull request that moves the project in the working directory to the newest
# release of the pipeline (bump.sh), or prints that it is on it already. Pre-releases
# count only with --pre.
host=$(cd "$(dirname "$0")" && pwd)
sub=.claude/skills/pipeline
pin=.claude/pipeline-release
fail() { echo "update-pipeline: $*" >&2; exit 1; }

filter=(--exclude-drafts --exclude-pre-releases)
case "$*" in
  "") ;;
  --pre) filter=(--exclude-drafts) ;;
  *) fail "usage: update-pipeline.sh [--pre]" ;;
esac
reason=$("$host/require-project-root.sh") || fail "$reason"
url=$(sed -n 's/^ *"repository": *"\([^"]*\)".*/\1/p' "$host/../.claude-plugin/plugin.json")
url=${url%/}
repo=${url#https://github.com/}
newest=$(gh release list --repo "$repo" "${filter[@]}" --limit 1 --json tagName --jq '.[0].tagName // ""') \
  || fail "listing the releases of $repo failed"
[ -n "$newest" ] || fail "$repo has no release"

default=$("$host/../bin/default-branch.py")
git fetch --quiet origin "$default"
if [ "$(git ls-tree "origin/$default" -- "$sub" | cut -d' ' -f1)" = 160000 ]; then
  git -C "$sub" fetch --quiet origin "+refs/tags/$newest:refs/tags/$newest" \
    || fail "fetching tag $newest of the pipeline failed, see above"
  current=$([ "$(git -C "$sub" rev-parse "refs/tags/$newest^{commit}")" = "$(git rev-parse "origin/$default:$sub")" ] && echo yes || true)
else
  current=$([ "$(git show "origin/$default:$pin" 2>/dev/null | tr -d '[:space:]')" = "$newest" ] && echo yes || true)
fi
if [ -n "$current" ]; then
  echo "up to date: $default pins $newest"
  exit
fi
exec "$host/bump.sh" "$newest"
