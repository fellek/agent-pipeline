---
description: Implement a GitHub issue and open a pull request
argument-hint: <issue-number> [maintainer-answer] [failure-summary]
context: fork
agent: pipeline:implementer
background: true
model: sonnet
effort: high
---

Work on GitHub issue #$0.

Maintainer answer to an earlier open question (empty if none): $1

Failure summary of the previous attempt (empty if none): $2
If set, check that cause first and do not repeat the same approach.

1. Read the issue with `issue-text.py $0`, which prints only the text you may read; do not read the issue or its comments any other way. If it exits non-zero, end with `STATUS: blocked` and its message as `SUMMARY`. Handle unclear scope or acceptance criteria as described in `${CLAUDE_PLUGIN_ROOT}/rules/workflow.md` under "Autopilot operation".
2. Check for an existing branch or PR for this issue. If one exists, continue there.
3. Otherwise create branch `issue-$0-<short-slug>` from the current default branch (printed by `default-branch.py`).
4. Implement the smallest change that satisfies the issue. Add or update tests.
5. Run the checks listed in `.claude/rules/project.md`. On failure read the logs first. Do not report `done` while a check fails.
6. Create a followup issue for each finding outside the scope, as described in `${CLAUDE_PLUGIN_ROOT}/rules/workflow.md`. List them in the PR description and the issue comment.
7. Use a sub agent to check the diff for duplicated code and wait for its result before pushing.
8. Push and open a PR to the default branch with `Closes #$0` in the description.
9. Post a brief comment on the issue: PR link, what was done, open points.
10. End with the result block from `${CLAUDE_PLUGIN_ROOT}/rules/workflow.md`.

Do not merge.
