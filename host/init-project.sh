#!/usr/bin/env bash
set -euo pipefail

# Sets up the project in the working directory for the pipeline: adds the pipeline
# <tag> as submodule, copies the templates without overwriting and creates the labels.
host=$(cd "$(dirname "$0")" && pwd)
sub=.claude/skills/pipeline
fail() { echo "init-project: $*" >&2; exit 1; }

[[ $# -eq 1 && -n $1 ]] || fail "usage: init-project.sh <tag>"
tag=$1
reason=$("$host/require-project-root.sh") || fail "$reason"
url=$(sed -n 's/^ *"repository": *"\([^"]*\)".*/\1/p' "$host/../.claude-plugin/plugin.json")

if [ -e "$sub" ]; then
  echo "kept $sub"
else
  # git's own message tells a missing tag from a network or auth error.
  git ls-remote --exit-code --tags "$url" "refs/tags/$tag" >/dev/null \
    || fail "tag $tag not found at $url, see above"
  git submodule add --quiet "$url" "$sub"
  git -C "$sub" checkout --quiet --detach "refs/tags/$tag"
  git add "$sub"
  echo "added $sub at $tag"
fi
# Lets pull and switch move the submodule along, so the working tree stays clean.
git config submodule.recurse true

# The templates hold .claude and .github without the dot, so Claude Code does not load
# them as rules of the pipeline repository itself.
templates=$sub/templates
while IFS= read -r file; do
  case $file in
    claude/* | github/*) dest=.$file ;;
    *) dest=$file ;;
  esac
  if [ -e "$dest" ]; then
    echo "kept $dest"
  else
    mkdir -p "$(dirname "$dest")"
    cp "$templates/$file" "$dest"
    echo "added $dest"
  fi
done < <(cd "$templates" && find . -type f ! -name LICENSE ! -name gitignore | sed 's|^\./||' | sort)

touch .gitignore
missing=$(grep -v '^#' "$templates/gitignore" | grep -vxF -f .gitignore || true)
if [ -n "$missing" ]; then
  { [ -z "$(tail -c1 .gitignore)" ] || echo; grep '^#' "$templates/gitignore"; echo "$missing"; } >> .gitignore
  echo "added .gitignore entries"
fi

labels=(
  "ready|0e8a16|Ready for the autopilot"
  "in-progress|fbca04|The autopilot works on it"
  "in-review|1d76db|The autopilot reviews the pull request"
  "approved|2ea44f|Review passed, waits for CI and merge"
  "question|d876e3|Waits for an answer from the maintainer"
  "parked|c5def5|Parked by the autopilot"
  "followup|bfdadc|Found while working on another issue"
  "infrastructure|5319e7|Changes the pipeline or its setup"
)
existing=$(gh label list --limit 1000 --json name --jq '.[].name')
for label in "${labels[@]}"; do
  IFS='|' read -r name color description <<< "$label"
  if grep -qxF "$name" <<< "$existing"; then
    echo "kept label $name"
  else
    gh label create "$name" --color "$color" --description "$description" >/dev/null
    echo "added label $name"
  fi
done

cat <<EOF

Manual steps:
- Review the changes and commit them.
- Start claude in the project once and accept the trust dialog, so it loads the plugin from $sub.
- Add the project's checks to .claude/rules/project.md and run them in CI, with the submodule checked out.
- Add the check commands to the allow list in .claude/settings.json, otherwise the autopilot stops at a permission prompt.
- GitHub settings, General: enable "Automatically delete head branches".
- GitHub settings, Rules: add a ruleset for the default branch that requires a pull request and the status checks agent-review and CI, and blocks force pushes and deletions.
- In every other clone, for example the autopilot's: git submodule update --init && git config submodule.recurse true
EOF
