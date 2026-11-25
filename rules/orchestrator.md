## Autopilot operation

The `/pipeline:autopilot` skill runs the pipeline unattended; setup in [docs/autopilot.md](../docs/autopilot.md). The steps follow [workflow.md](workflow.md); these rules hold for the orchestrator only, `autopilot-state.py` enforces them.

- The maintainer is reached only via Telegram, never via AskUserQuestion. Telegram answers are mirrored as issue comments. A Telegram answer counts only with the prefix `#<n>`.
- At most 3 attempts per step; then report via Telegram and park the issue (the pipeline goes on with the next one). Parking pushes the branch first; `pause` is a separate state that stops the whole pipeline.
- At most 5 review rounds: after the 3rd the maintainer gets an info without parking, after the 5th the issue is parked for the maintainer.
- At most 15 started steps per issue, then the issue is parked with `Budget`; resuming it grants 15 more. At most 50 started steps per UTC day over all issues, then the pipeline pauses and `weiter` grants 50 more.
- Nothing is deleted without approval via Telegram.
- After a merge that moves the pinned pipeline release the autopilot restarts on it, so no further issue runs with the old release.
