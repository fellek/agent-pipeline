---
description: Review the pull request that was created for a GitHub issue
argument-hint: <issue-number> [unused] [failure-summary]
context: fork
agent: reviewer
background: false
---

Review the pull request that was created for issue #$0.

Failure summary of the previous attempt (empty if none): $2
If set, check that cause first and do not repeat the same approach.

1. Find the open PR for the issue (branch `issue-$0-*` or `Closes #$0` in the description). If there is none or more than one, end with `STATUS: blocked`.
2. Check out the PR branch. Read the issue, the PR description and all existing review comments.
3. Run the checks listed in `.claude/rules/project.md`.
4. Review the diff for: acceptance criteria of the issue, rules in CLAUDE.md, correctness and edge cases, missing tests, changes outside the scope of the issue. Also check the choices the implementer made on open points: they must follow from the project rules.
5. Resolve each unresolved review thread whose finding the current diff addresses or whose reply you accept (moved to a new issue, valid reason) (GraphQL mutation `resolveReviewThread`); leave the others open. Do not approve while any thread stays open.
6. Submit one review as a comment review. Inline comment per finding: what, why, suggested fix. First line of the summary: `Verdict: approve` or `Verdict: changes requested`.
7. End with the result block from CLAUDE.md, including the `VERDICT` line.

Do not change code and do not merge.
