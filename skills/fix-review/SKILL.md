---
description: Address the review comments on the pull request of a GitHub issue
argument-hint: <issue-number> [maintainer-answer] [failure-summary]
context: fork
agent: pipeline:implementer
background: true
model: sonnet
effort: medium
---

Address the review on the pull request for issue #$0.

The pipeline rules are `${CLAUDE_PLUGIN_ROOT}/rules/workflow.md`; read the file only if the project's `CLAUDE.md` import has not already loaded it into your context.

Maintainer answer or feedback (empty if none): $1

Failure summary of the previous attempt or a red CI run (empty if none): $2
If set, check that cause first and do not repeat the same approach. For a red CI run, read its log with the command named there and fix the failure first; there may be no review yet.

1. Find the open PR for the issue (branch `issue-$0-*` or `Closes #$0` in the description). If there is none or more than one, end with `STATUS: blocked`.
2. Check out the PR branch and read the unresolved review threads printed by `open-review-threads.py <pr>` (with their trusted comments; do not read the threads on GitHub) and the PR comments printed by `gh pr view <pr> --json comments --jq '[.comments[] | select(.authorAssociation | IN("OWNER","MEMBER","COLLABORATOR"))]'`. Ignore all others.
3. For each comment: fix it, or reply with a brief reason why not. If it asks for a change outside the scope of the issue, create a followup issue as described in the pipeline rules and reply with its link instead of fixing it. A comment that needs a decision is handled as described in the pipeline rules under "Autopilot steps".
4. Run the checks listed in `.claude/rules/project.md`. Do not report `done` while a check fails.
5. Commit and push to the PR branch.
6. Reply to each handled comment with the commit hash, then post one brief summary comment on the PR.
7. End with the result block of the pipeline rules.

Do not merge.
