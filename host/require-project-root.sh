#!/usr/bin/env bash
set -euo pipefail

# Fails with the reason on stdout unless the working directory is the root of the
# project: state lives in .pipeline/ there, and a subdirectory, or the plugin's own
# submodule or release worktree, would get a .pipeline/ of its own.
plugin=$(cd "$(dirname "$0")/.." && pwd -P)
here=$(pwd -P)

command -v git >/dev/null || {
  echo "git is missing"
  exit 1
}
root=$(git rev-parse --show-toplevel 2>/dev/null) && [ "$root" = "$here" ] || {
  echo "run it in the project root"
  exit 1
}
# A plain clone of the plugin repository is its own project; a submodule or linked
# worktree of it is the plugin used by another project.
if [ "$here" = "$plugin" ] && {
  [ -n "$(git rev-parse --show-superproject-working-tree)" ] ||
    [ "$(git rev-parse --absolute-git-dir)" != "$(git rev-parse --path-format=absolute --git-common-dir)" ]
}; then
  echo "run it in the project root, not in the plugin"
  exit 1
fi
