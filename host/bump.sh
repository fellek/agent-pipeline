#!/usr/bin/env bash
set -euo pipefail

# Opens a pull request in the project in the working directory that moves the pipeline
# to <tag>, with the release notes: in a project the submodule, in the pipeline
# repository itself the tag in .claude/pipeline-release.
host=$(cd "$(dirname "$0")" && pwd)
sub=.claude/skills/pipeline
pin=.claude/pipeline-release
fail() { echo "bump: $*" >&2; exit 1; }

[[ $# -eq 1 && -n $1 ]] || fail "usage: bump.sh <tag>"
tag=$1
branch=bump-pipeline-$tag
reason=$("$host/require-project-root.sh") || fail "$reason"
if [ "$(git ls-files --stage -- "$sub" | cut -d' ' -f1)" != 160000 ] && [ -f "$pin" ]; then
  target=$pin
else
  target=$sub
  [ -e "$sub/.git" ] || fail "$sub is no submodule, see init-project.sh"
fi
[ -z "$(git status --porcelain)" ] || fail "the working tree has changes"
git check-ref-format --branch "$branch" >/dev/null || fail "invalid tag: $tag"
! git rev-parse --verify --quiet "refs/heads/$branch" >/dev/null || fail "branch $branch exists"

default=$("$host/../bin/default-branch.py")
git fetch --quiet origin "$default"
if [ "$target" = "$sub" ]; then
  # git's own message tells a missing tag from a network or auth error.
  git -C "$sub" fetch --quiet origin "+refs/tags/$tag:refs/tags/$tag" \
    || fail "fetching tag $tag of the pipeline failed, see above"
  new=$(git -C "$sub" rev-parse "refs/tags/$tag^{commit}")
  old=$(git rev-parse "origin/$default:$sub")
  [ "$new" != "$old" ] || fail "$sub is at $tag on $default already"
  old_name=$(git -C "$sub" describe --tags --exact-match "$old" 2>/dev/null || git -C "$sub" rev-parse --short "$old")
  url=$(git -C "$sub" config remote.origin.url)
else
  git fetch --quiet origin "+refs/tags/$tag:refs/tags/$tag" \
    || fail "fetching tag $tag of the pipeline failed, see above"
  old_name=$(git show "origin/$default:$pin" 2>/dev/null | tr -d '[:space:]') || old_name=none
  [ "$old_name" != "$tag" ] || fail "$pin is at $tag on $default already"
  url=$(git config remote.origin.url)
fi

url=${url%/}
url=${url%.git}
owner=${url%/*}
repo=${owner##*[/:]}/${url##*/}
notes=$(gh release view "$tag" --repo "$repo" --json body --jq .body) \
  || fail "reading the release notes of $tag in $repo failed"

git switch --quiet --no-track -c "$branch" "origin/$default"
# Back to the previous checkout, with the submodule where that checkout has it.
trap 'git checkout --quiet --recurse-submodules -' EXIT
if [ "$target" = "$sub" ]; then
  git -C "$sub" checkout --quiet --detach "$new"
else
  printf '%s\n' "$tag" >"$pin"
fi
git add "$target"
git commit --quiet -m "Bump pipeline to $tag"
git push --quiet -u origin "$branch"
gh pr create --base "$default" --head "$branch" \
  --title "Bump pipeline to $tag" \
  --body "Moves \`$target\` from $old_name to $tag.

## Release notes

$notes"
git checkout --quiet --recurse-submodules -
trap - EXIT
# The pushed branch holds the change; a later bump to the same tag, as by a rollback,
# would otherwise refuse.
git branch --quiet -D "$branch"
