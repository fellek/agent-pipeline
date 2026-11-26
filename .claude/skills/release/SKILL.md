---
description: Prepare a release of the pipeline: ask for major, minor or patch, open the version bump PR, then give the root command that starts the workflow release
model: haiku
effort: low
disable-model-invocation: true
---

Run each command from the repository root, as written, and show the maintainer its output unchanged.

1. Run `host/release-pipeline.sh` and ask the maintainer with AskUserQuestion which level to release: major, minor or patch, each option with the version from the output. Stop if they choose none.
2. Run `host/release-pipeline.sh <level>`. If it fails, show the error and stop.
3. The output is either the bump PR with the root commands for review and merge, or, once that PR is merged, the root command `gate release` that starts the workflow. Never run these commands yourself and never start the workflow in another way: only the maintainer starts a release, as root. After the merge, the maintainer runs `/release` again and picks the same level.
