---
description: Address the review comments on the pull request of a GitHub issue
argument-hint: <issue-number> [maintainer-answer]
context: fork
agent: implementer
background: false
---

Address the review on the pull request for issue #$0.

Maintainer answer or feedback (empty if none): $1

1. Find the open PR for the issue (branch `issue-$0-*` or `Closes #$0` in the description). If there is none or more than one, end with `STATUS: blocked`.
2. Check out the PR branch and read all unresolved review comments and PR comments.
3. For each comment: fix it, or reply with a brief reason why not. A comment that needs a decision is handled as described in CLAUDE.md under "Autopilot operation".
4. Run the checks listed in `.claude/rules/project.md`. Do not report `done` while a check fails.
5. Commit and push to the PR branch.
6. Reply to each handled comment with the commit hash, then post one brief summary comment on the PR.
7. End with the result block from CLAUDE.md.

Do not merge.
