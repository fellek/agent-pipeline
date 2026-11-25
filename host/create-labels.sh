#!/usr/bin/env bash
set -euo pipefail

# Creates the labels of the pipeline that the repository in the working directory
# lacks; existing labels keep their color and description.
labels=(
  "ready|0e8a16|Ready for the autopilot"
  "in-progress|fbca04|The autopilot works on it"
  "in-review|1d76db|The autopilot reviews the pull request"
  "approved|2ea44f|Review passed, waits for CI and merge"
  "question|d876e3|Waits for an answer from the maintainer"
  "parked|c5def5|Parked by the autopilot"
  "followup|bfdadc|Found while working on another issue"
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
