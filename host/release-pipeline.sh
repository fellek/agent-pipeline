#!/usr/bin/env bash
set -euo pipefail

# Prepares a release of the pipeline repository in the working directory, one level
# above its newest release. Without a level it prints the version of each level. With
# one it opens the pull request that sets that version in plugin.json, and once that is
# merged prints the root command that starts the workflow release: the update timer of
# every host installs a release, so the session never starts one itself.
host=$(cd "$(dirname "$0")" && pwd)
pin=.claude/pipeline-release
manifest=.claude-plugin/plugin.json
fail() { echo "release-pipeline: $*" >&2; exit 1; }

case "$*" in
  "" | major | minor | patch) level=${1:-} ;;
  *) fail "usage: release-pipeline.sh [major|minor|patch]" ;;
esac
reason=$("$host/require-project-root.sh") || fail "$reason"
[ -f "$pin" ] && [ -f .github/workflows/release.yml ] || fail "run it in the pipeline repository"
url=$(sed -n 's/^ *"repository": *"\([^"]*\)".*/\1/p' "$host/../$manifest")
url=${url%/}
repo=${url#https://github.com/}
newest=$(gh release list --repo "$repo" --exclude-drafts --limit 1 --json tagName --jq '.[0].tagName // ""') \
  || fail "listing the releases of $repo failed"
[[ $newest =~ ^v([0-9]+)\.([0-9]+)\.([0-9]+)$ ]] || fail "newest release ${newest:-(none)} is no v<major>.<minor>.<patch>"
major=$((BASH_REMATCH[1] + 1)).0.0
minor=${BASH_REMATCH[1]}.$((BASH_REMATCH[2] + 1)).0
patch=${BASH_REMATCH[1]}.${BASH_REMATCH[2]}.$((BASH_REMATCH[3] + 1))
if [ -z "$level" ]; then
  echo "Release nach $newest: major v$major, minor v$minor, patch v$patch"
  exit
fi
next=${!level}
user=$(id -un)

default=$("$host/../bin/default-branch.py")
git fetch --quiet origin "$default"
version=$(git show "origin/$default:$manifest" | sed -n 's/^ *"version": *"\([^"]*\)".*/\1/p')
if [ "$version" = "$next" ]; then
  sha=$(git rev-parse "origin/$default")
  echo "$default hat v$next. Release starten, als root; Update-Hinweise als weiteres Argument:"
  echo "sudo -u pipeline-gate /opt/pipeline/gate release $user v$next $sha"
  exit
fi
[ "$version" = "${newest#v}" ] || fail "$default has version $version, neither ${newest#v} nor $next"

branch=bump-plugin-$next
open=$(gh pr list --head "$branch" --state open --json number,headRefOid,url \
  --jq '.[0] // empty | "\(.number) \(.headRefOid) \(.url)"') || fail "listing the pull requests of $branch failed"
if [ -n "$open" ]; then
  read -r pr sha link <<<"$open"
else
  [ -z "$(git status --porcelain)" ] || fail "the working tree has changes"
  ! git rev-parse --verify --quiet "refs/heads/$branch" >/dev/null || fail "branch $branch exists"
  git switch --quiet --no-track -c "$branch" "origin/$default"
  # Back to the previous checkout, with the submodule where that checkout has it.
  trap 'git checkout --quiet --recurse-submodules -' EXIT
  changed=$(sed "s/^\( *\"version\": *\"\)[^\"]*\"/\1$next\"/" "$manifest")
  printf '%s\n' "$changed" >"$manifest"
  git add "$manifest"
  git commit --quiet -m "Bump plugin to $next"
  sha=$(git rev-parse HEAD)
  git push --quiet -u origin "$branch"
  link=$(gh pr create --base "$default" --head "$branch" \
    --title "Bump plugin to $next" --body "Version $next for the release v$next ($level).")
  git checkout --quiet --recurse-submodules -
  trap - EXIT
  git branch --quiet -D "$branch"
  pr=${link##*/}
fi
echo "$link"
echo "Nach grüner CI als root, danach erneut release $level:"
echo "sudo -u pipeline-gate /opt/pipeline/gate review --manual $user $pr $sha approve"
echo "sudo -u $user sudo -n -u pipeline-gate /opt/pipeline/gate merge $pr $sha"
