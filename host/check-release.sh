#!/usr/bin/env bash
set -euo pipefail

# Warns and fails unless .claude/skills/pipeline of the project in the working
# directory holds the pinned release: in a project the submodule's recorded commit,
# in the pipeline repository the tag in .claude/pipeline-release. Without it Claude
# Code silently loads no pipeline rules, skills or hook.
sub=.claude/skills/pipeline
pin=.claude/pipeline-release
warn() {
  echo "Warning: $*. This session runs without the pinned pipeline release, see INSTALL.md of the pipeline."
  exit 1
}

if [ "$(git ls-files --stage -- "$sub" | cut -d' ' -f1)" = 160000 ]; then
  case $(git submodule status -- "$sub" | cut -c1) in
    -) warn "submodule $sub is not initialized, run git submodule update --init" ;;
    +) warn "submodule $sub is not on its recorded commit, run git submodule update" ;;
    U) warn "submodule $sub has a merge conflict" ;;
  esac
elif [ -f "$pin" ]; then
  tag=$(tr -d '[:space:]' <"$pin")
  [ -n "$tag" ] || warn "$pin is empty"
  want=$(git rev-parse -q --verify "refs/tags/$tag^{commit}") \
    || warn "tag $tag of $pin is not fetched, run host/use-release.sh"
  have=$(git -C "$sub" rev-parse -q --verify HEAD 2>/dev/null) || have=
  [ "$have" = "$want" ] || warn "$sub is not on $tag of $pin, run host/use-release.sh"
else
  warn "neither a submodule $sub nor $pin pins a pipeline release"
fi
