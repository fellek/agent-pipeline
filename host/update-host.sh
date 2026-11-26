#!/usr/bin/env bash
set -euo pipefail

# Finishes the pipeline update of the autopilot of Linux user <user>, as root from the
# maintainer's clone of the pipeline: shows the bump pull request that `update` opened,
# checks that it pins exactly the release tag, posts the maintainer's approve, merges
# it through the gate once its runs passed and installs the gate of the new release.
# The autopilot then restarts on the release by itself.
host=$(cd "$(dirname "$0")" && pwd)
plugin=${host%/host}
# Prefix of the system paths, for the tests only.
root=${GATE_ROOT:-}
gate=$root/opt/pipeline/gate
sub=.claude/skills/pipeline
pin=.claude/pipeline-release
fail() { echo "update-host: $*" >&2; exit 1; }

[ $# -eq 1 ] || fail "usage: update-host.sh <user>"
user=$1
[ -n "$root" ] || [ "$(id -u)" = 0 ] || fail "run as root"
store=$root/etc/pipeline-gate/projects/$user
[ -s "$store/repo" ] || fail "no gate for $user, see install-gate.sh"
repo=$(cat "$store/repo")
owner=$(stat -c %U "$plugin")
# Root runs the code of this clone, so the autopilot must not be able to change it.
[ "$owner" != "$user" ] || fail "$plugin belongs to $user, run the maintainer's clone of the pipeline"
cd /

# The gate selects the project by its calling user.
gate_as_user() { sudo -u "$user" sudo -n -u pipeline-gate "$gate" "$@" </dev/null; }
git_as_owner() { sudo -u "$owner" git -C "$plugin" "$@"; }

bumps=$(gate_as_user gh pr list --state open --json number,headRefName,headRefOid,title,url \
  --jq '.[] | select(.headRefName | startswith("bump-pipeline-")) | [.number, .headRefOid, .title, .url] | @tsv') \
  || fail "listing the pull requests of $repo failed, see above"
[ -n "$bumps" ] || fail "$repo has no open bump pull request, send update to the bot first"
[ "$(wc -l <<<"$bumps")" -eq 1 ] || fail "$repo has several open bump pull requests, close all but one:
$bumps"
IFS=$'\t' read -r number sha title url <<<"$bumps"
tag=${title#Bump pipeline to }
[ "$tag" != "$title" ] && git check-ref-format "refs/tags/$tag" || fail "#$number is no bump: $title"

git_as_owner fetch --quiet origin "+refs/tags/$tag:refs/tags/$tag" \
  || fail "fetching tag $tag into $plugin failed, see above"
files=$(gate_as_user gh pr view "$number" --json files --jq '.files[].path')
case $files in
  "$sub") want=$(git_as_owner rev-parse "refs/tags/$tag^{commit}") ;;
  "$pin") want=$tag ;;
  *) fail "#$number changes more than the pinned release: $(paste -sd ' ' <<<"$files")" ;;
esac
have=$(gate_as_user gh api "repos/$repo/contents/$files?ref=$sha" \
  --jq 'if .type == "submodule" then .sha else .content | @base64d end')
[ "$(tr -d '[:space:]' <<<"$have")" = "$want" ] || fail "#$number pins $have, not $tag"

echo "$url: $title"
gate_as_user gh pr view "$number" --json body --jq .body
read -rp "Approve and merge #$number, then install the gate of $tag? [y/N] " answer || true
[ "$answer" = y ] || fail "nothing done"

sudo -u pipeline-gate "$gate" review --manual "$user" "$number" "$sha" approve </dev/null
# Only a refusal that waits on runs clears by itself: CI that is still running, or a
# ruleset whose required check agent-review has not yet seen the approve.
pending() {
  local problem
  while IFS= read -r problem; do
    case $problem in
      "runs not passed: "*)
        [ "$(gate_as_user gh run list --commit "$sha" --json status \
          --jq 'map(select(.status != "completed")) | length')" != 0 ] || return 1 ;;
      "gh pr merge failed: "*"status check"*) ;;
      *) return 1 ;;
    esac
  done < <(sed 's/^gate: //; s/; /\n/g' <<<"$1")
}
last=
tries=0
until out=$(gate_as_user merge "$number" "$sha" 2>&1); do
  pending "$out" || fail "merging #$number failed: $out"
  tries=$((tries + 1))
  [ $tries -lt 60 ] || fail "#$number still not mergeable after 30 minutes: $out; run update-host.sh $user again"
  [ "$out" = "$last" ] || echo "waiting: $out"
  last=$out
  sleep 30
done
echo "merged #$number"

tree=$(mktemp -d)
trap 'rm -rf "$tree"' EXIT
git_as_owner archive "refs/tags/$tag" | tar -x -C "$tree"
"$tree/host/install-gate.sh" "$user" "$repo" </dev/null >/dev/null
echo "gate of $tag installed; the autopilot restarts on $tag within a minute when idle, otherwise before its next issue"
