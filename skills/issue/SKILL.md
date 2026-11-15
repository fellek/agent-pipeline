---
description: Implement a GitHub issue and open a pull request
argument-hint: <issue-number> [maintainer-answer] [failure-summary]
context: fork
agent: implementer
background: true
model: sonnet
effort: high
---

Work on GitHub issue #$0.

Maintainer answer to an earlier open question (empty if none): $1

Failure summary of the previous attempt (empty if none): $2
If set, check that cause first and do not repeat the same approach.

1. Read the issue and all its comments. Handle unclear scope or acceptance criteria as described in CLAUDE.md under "Autopilot operation".
2. Check for an existing branch or PR for this issue. If one exists, continue there.
3. Otherwise create branch `issue-$0-<short-slug>` from the current `master`.
4. Implement the smallest change that satisfies the issue. Add or update tests.
5. Run the checks listed in `.claude/rules/project.md`. On failure read the logs first. Do not report `done` while a check fails.
6. Use a sub agent to check the diff for duplicated code and wait for its result before pushing.
7. Push and open a PR to `master` with `Closes #$0` in the description.
8. Post a brief comment on the issue: PR link, what was done, open points.
9. End with the result block from CLAUDE.md.

Do not merge.
