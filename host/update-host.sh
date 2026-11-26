#!/usr/bin/env bash
set -euo pipefail

# Updates the pipeline of the autopilot of Linux user <user>, as root. install-gate.sh
# installs it as /opt/pipeline/update-host, owned by root, so the autopilot cannot
# change what root runs; it fetches each release into a temporary directory.
#
# The maintainer runs it for the bump pull request that `update` opened: it checks that
# the pull request pins exactly the release tag, asks, posts the maintainer's approve,
# merges it through the gate once its runs passed and installs the gate and the Claude
# Code version of the release. With --auto the timer pipeline-update@<user> runs it: it
# opens the bump pull request to the newest stable release, announces it via Telegram
# and merges it 12 hours later, only for a published stable release whose tag is on the
# default branch of the pipeline. Closing the bump pull request keeps the timer from
# that release. The autopilot then restarts on the release by itself.
# Prefix of the system paths, for the tests only.
root=${GATE_ROOT:-}
gate=$root/opt/pipeline/gate
sub=.claude/skills/pipeline
pin=.claude/pipeline-release
state=$root/var/lib/pipeline-update
delay=$((12 * 3600))
auto=
project=
fail() {
  echo "update-host: $*" >&2
  [ -z "$auto" ] || notify_once "Pipeline-Update gescheitert: $*"
  exit 1
}
# Every failure of the timer reaches the maintainer, not only the journal.
trap 'fail "line $LINENO failed, see journalctl -u pipeline-update@${user-}"' ERR

# The gate selects the project by its calling user.
gate_as_user() { sudo -u "$user" sudo -n -u pipeline-gate "$gate" "$@" </dev/null; }
# The autopilot's own script sends it, with the bot and chat of the project.
notify() {
  [ -n "$project" ] || return 1
  printf '%s\n' "$1" | sudo -u "$user" -H bash -c 'cd "$1" && exec .claude/skills/pipeline/bin/telegram-send.py' \
    _ "$project" >/dev/null 2>&1
}
# The timer would repeat a lasting failure every run.
notify_once() {
  [ "$(cat "$state/$user.error" 2>/dev/null)" != "$1" ] || return 0
  printf '%s\n' "$1" 2>/dev/null >"$state/$user.error" || true
  notify "$1" || true
}
# The commit of a release tag of the pipeline.
tag_commit() {
  git ls-remote "$pipeline_url" "refs/tags/$1" "refs/tags/$1^{}" | tail -1 | cut -f1
}
# A closed, unmerged bump pull request is the maintainer's veto against its release.
vetoed() {
  local count
  count=$(gate_as_user gh pr list --state closed --limit 100 --json title,mergedAt \
    --jq "[.[] | select(.title == \"Bump pipeline to $1\" and .mergedAt == null)] | length") \
    || fail "listing the closed bump pull requests of $repo failed"
  [ "$count" != 0 ]
}
# What the pin at <ref> holds: the tag name in .claude/pipeline-release, else the
# commit of the submodule.
pinned_at() {
  gate_as_user gh api "repos/$repo/contents/$pin?ref=$1" --jq '.content | @base64d' 2>/dev/null \
    || gate_as_user gh api "repos/$repo/contents/$sub?ref=$1" --jq .sha
}
# Opens the bump pull request as the autopilot would on `update`, in a clone of its
# own that it deletes, so the working tree of the running autopilot stays untouched.
open_bump() {
  sudo -u "$user" -H bash -c '
    set -euo pipefail
    tmp=$(mktemp -d)
    trap "rm -rf \"$tmp\"" EXIT
    git clone --quiet --recurse-submodules "https://github.com/$1" "$tmp/project"
    cd "$tmp/project"
    if [ -f "$2" ]; then host/update-pipeline.sh; else "$3/host/update-pipeline.sh"; fi
  ' _ "$repo" "$pin" "$sub"
}

if [ "${1-}" = --auto ]; then
  auto=yes
  shift
fi
[ $# -eq 1 ] || fail "usage: update-host [--auto] <user>"
user=$1
[ -n "$root" ] || [ "$(id -u)" = 0 ] || fail "run as root"
if [ -n "$auto" ]; then
  mkdir -p "$state"
  chmod 0700 "$state"
  home=$(getent passwd "$user" | cut -d: -f6)
  project=$(sed -n 's/^WorkingDirectory=//p' "$home"/.config/systemd/user/autopilot-*.service 2>/dev/null | head -1) || true
  # Without Telegram nobody learns of an update in time to veto it.
  [ -n "$project" ] || fail "no autopilot service of $user, so no Telegram to announce updates"
fi
store=$root/etc/pipeline-gate/projects/$user
[ -s "$store/repo" ] || fail "no gate for $user, see install-gate.sh"
repo=$(cat "$store/repo")
pipeline_repo=$(cat "$root/opt/pipeline/pipeline-repo") || fail "run install-gate.sh of a newer release"
pipeline_url=https://github.com/$pipeline_repo
cd /

bumps=$(gate_as_user gh pr list --state open --json number,headRefName,headRefOid,title,url \
  --jq '.[] | select(.headRefName | startswith("bump-pipeline-")) | [.number, .headRefOid, .title, .url] | @tsv') \
  || fail "listing the pull requests of $repo failed, see above"
if [ -n "$auto" ]; then
  newest=$(gate_as_user gh release list --repo "$pipeline_repo" --exclude-drafts --exclude-pre-releases \
    --limit 1 --json tagName --jq '.[0].tagName // ""') || fail "listing the releases of $pipeline_repo failed"
  [[ $newest =~ ^[A-Za-z0-9._-]+$ ]] || fail "$pipeline_repo has no stable release"
fi
if [ -z "$bumps" ]; then
  [ -n "$auto" ] || fail "$repo has no open bump pull request, send update to the bot first"
  pinned=$(pinned_at HEAD | tr -d '[:space:]') || fail "reading the pinned release of $repo failed"
  if [ "$pinned" != "$newest" ] && [ "$pinned" != "$(tag_commit "$newest")" ]; then
    vetoed "$newest" || open_bump >/dev/null || fail "opening the bump pull request to $newest failed"
  fi
  rm -f "$state/$user.error"
  exit 0
fi
[ "$(wc -l <<<"$bumps")" -eq 1 ] || fail "$repo has several open bump pull requests, close all but one:
$bumps"
IFS=$'\t' read -r number sha title url <<<"$bumps"
tag=${title#Bump pipeline to }
[[ $tag != "$title" && $tag =~ ^[A-Za-z0-9._-]+$ ]] || fail "#$number is no bump: $title"
if [ -n "$auto" ]; then
  # The session can open a bump too: the timer takes only the newest release, so no
  # downgrade, and none the maintainer vetoed. Other bumps are the manual path's.
  [ "$tag" = "$newest" ] || fail "#$number bumps to $tag, not to the newest release $newest; close it or run update-host $user"
  ! vetoed "$tag" || fail "#$number bumps to $tag, which a closed bump pull request vetoed; close it or run update-host $user"
fi

tree=$(mktemp -d)
trap 'rm -rf "$tree"' EXIT
git init --quiet --bare "$tree/git"
git -C "$tree/git" fetch --quiet "$pipeline_url" "+refs/tags/$tag:refs/tags/$tag" "+HEAD:refs/heads/default" \
  || fail "fetching tag $tag of $pipeline_repo failed, see above"
files=$(gate_as_user gh pr view "$number" --json files --jq '.files[].path')
case $files in
  "$sub") want=$(git -C "$tree/git" rev-parse "refs/tags/$tag^{commit}") ;;
  "$pin") want=$tag ;;
  *) fail "#$number changes more than the pinned release: $(paste -sd ' ' <<<"$files")" ;;
esac
have=$(gate_as_user gh api "repos/$repo/contents/$files?ref=$sha" \
  --jq 'if .type == "submodule" then .sha else .content | @base64d end')
[ "$(tr -d '[:space:]' <<<"$have")" = "$want" ] || fail "#$number pins $have, not $tag"

if [ -n "$auto" ]; then
  # Only a release of the pipeline's default branch, which only gate merge reaches
  # after CI and the gate's review, gets root without the maintainer.
  stable=$(gate_as_user gh release view "$tag" --repo "$pipeline_repo" --json isDraft,isPrerelease \
    --jq '(.isDraft or .isPrerelease) | not') || fail "reading release $tag of $pipeline_repo failed"
  [ "$stable" = true ] || fail "$tag is no published stable release of $pipeline_repo"
  git -C "$tree/git" merge-base --is-ancestor "refs/tags/$tag^{commit}" refs/heads/default \
    || fail "$tag is not on the default branch of $pipeline_repo"
  announced=$state/$user-$sha
  if [ ! -e "$announced" ]; then
    # The wait starts only once the maintainer can know of the update.
    notify "Pipeline-Update auf $tag ($url) folgt ab $(date -d "@$(($(date +%s) + delay))" '+%d.%m. %H:%M'). Abbrechen: PR schließen. Sofort, als root: /opt/pipeline/update-host $user" \
      || fail "announcing $tag via Telegram failed"
    touch "$announced"
    exit 0
  fi
  [ $(($(date +%s) - $(stat -c %Y "$announced"))) -ge $delay ] || exit 0
else
  echo "$url: $title"
  gate_as_user gh pr view "$number" --json body --jq .body
  read -rp "Approve and merge #$number, then install the gate of $tag? [y/N] " answer || true
  [ "$answer" = y ] || fail "nothing done"
fi

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
approved=
until out=$(gate_as_user merge "$number" "$sha" 2>&1); do
  # A merge attempt first, so a rerun posts no second approve.
  if [ -z "$approved" ] && grep -q "no attested approve on" <<<"$out"; then
    sudo -u pipeline-gate "$gate" review --manual "$user" "$number" "$sha" approve </dev/null >/dev/null
    approved=yes
    continue
  fi
  pending "$out" || fail "merging #$number failed: $out"
  tries=$((tries + 1))
  [ $tries -lt 60 ] || fail "#$number still not mergeable after 30 minutes: $out; run update-host $user again"
  [ "$out" = "$last" ] || echo "waiting: $out"
  last=$out
  sleep 30
done
echo "merged #$number"

mkdir "$tree/src"
git -C "$tree/git" archive "refs/tags/$tag" | tar -x -C "$tree/src"
"$tree/src/host/install-gate.sh" "$user" "$repo" </dev/null >/dev/null || fail "installing the gate of $tag failed"
version=$(. "$tree/src/host/versions.sh" && echo "$claude_code")
for account in pipeline-gate "$user"; do
  sudo -u "$account" -H bash -c 'cd && c=.local/bin/claude && {
    [ ! -x "$c" ] || [ "$("$c" --version | cut -d" " -f1)" = "$1" ] || "$c" install "$1" >/dev/null; }' _ "$version" \
    || fail "installing Claude Code $version for $account failed"
done
echo "gate and Claude Code $version of $tag installed; the autopilot restarts on $tag within a minute when idle, otherwise before its next issue"
if [ -n "$auto" ]; then
  rm -f "$state/$user.error" "$state/$user-$sha"
  notify "Pipeline-Update auf $tag installiert, der Autopilot startet darauf neu." || true
fi
