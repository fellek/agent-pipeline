---
description: Implement a GitHub issue and open a pull request
argument-hint: <issue-number>
---

Work on GitHub issue #$ARGUMENTS.

1. Read the issue and all its comments. If scope or acceptance criteria are unclear, post your questions as an issue comment and stop.
2. Check for an existing branch or PR for this issue. If one exists, continue there.
3. Otherwise create branch `issue-$ARGUMENTS-<short-slug>` from the current `master`.
4. Implement the smallest change that satisfies the issue. Add or update tests.
5. Run the checks listed in `.claude/rules/project.md`. On failure read the logs first.
6. Use a sub agent to check the diff for duplicated code.
7. Push and open a PR to `master` with `Closes #$ARGUMENTS` in the description.
8. Post a brief comment on the issue: PR link, what was done, open points.

Do not merge.
