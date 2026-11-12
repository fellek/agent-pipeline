---
description: Address the review comments on the pull request of a GitHub issue
argument-hint: <issue-number>
---

Address the review on the pull request for issue #$ARGUMENTS.

1. Find the open PR for the issue (branch `issue-$ARGUMENTS-*` or `Closes #$ARGUMENTS` in the description). If there is none or more than one, report that and stop.
2. Check out the PR branch and read all unresolved review comments.
3. For each comment: fix it, or reply with a brief reason why not. If a comment needs a decision, ask in the thread and leave it open.
4. Run the checks listed in `.claude/rules/project.md`.
5. Commit and push to the PR branch.
6. Reply to each handled comment with the commit hash, then post one brief summary comment on the PR.

Do not merge.
