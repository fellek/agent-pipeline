#!/usr/bin/env bash
set -euo pipefail

# Name of the tmux session and systemd unit of the project in the working directory:
# autopilot-<repository name>, from the origin URL or else the directory name.
url=$(git remote get-url origin 2>/dev/null || true)
if [ -n "$url" ]; then
  # The last part after "/" or ":", so scp-style URLs like host:app.git work too.
  url=${url%/}
  repo=${url##*[/:]}
  repo=${repo%.git}
else
  repo=$(basename "$PWD")
fi
# tmux turns "." and ":" in session names into "_".
echo "autopilot-${repo//[^A-Za-z0-9_-]/-}"
