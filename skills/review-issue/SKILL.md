---
description: Review the pull request that was created for a GitHub issue
argument-hint: <issue-number>
---

Review the pull request that was created for issue #$ARGUMENTS.

1. Find the open PR for the issue (branch `issue-$ARGUMENTS-*` or `Closes #$ARGUMENTS` in the description). If there is none or more than one, report that and stop.
2. Check out the PR branch. Read the issue, the PR description and all existing review comments.
3. Run the checks listed in `.claude/rules/project.md`.
4. Review the diff for: acceptance criteria of the issue, rules in CLAUDE.md, correctness and edge cases, missing tests, changes outside the scope of the issue.
5. Submit one review as a comment review. Inline comment per finding: what, why, suggested fix. First line of the summary: `Verdict: approve` or `Verdict: changes requested`.

Do not change code and do not merge.
