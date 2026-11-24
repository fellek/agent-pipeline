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

"$host/create-labels.sh"

cat <<EOF

Manual steps:
- Review the changes and commit them.
- Start claude in the project once and accept the trust dialog, so it loads the plugin from $sub.
- Add the project's checks to .claude/rules/project.md and run them in CI, with the submodule checked out.
- Add the check commands to the allow list in .claude/settings.json, otherwise every check run waits for an approval.
- GitHub settings, General: enable "Automatically delete head branches".
- GitHub settings, Rules: add a ruleset for the default branch that requires a pull request and the status checks agent-review and CI, and blocks force pushes and deletions.
- In every other clone, for example the autopilot's: git submodule update --init && git config submodule.recurse true
EOF
