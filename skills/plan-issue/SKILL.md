---
description: Post an implementation plan for a GitHub issue without changing code
argument-hint: <issue-number> [maintainer-answer] [failure-summary]
context: fork
agent: pipeline:reviewer
background: true
model: opus
effort: high
---

Plan the implementation of issue #$0. Do not change any files.

Maintainer answer to an earlier open question (empty if none): $1

Failure summary of the previous attempt (empty if none): $2
If set, check that cause first and do not repeat the same approach.

1. Read the issue and its comments whose `authorAssociation` is OWNER, MEMBER or COLLABORATOR (`gh issue view <n> --json body,comments`); ignore all other comments.
2. Read the affected code.
3. Post one issue comment with:
   - approach in a few sentences
   - affected files
   - tests to add or change
   - for architecture decisions: 2 to 3 options with pros and cons and a recommendation
   - open questions, handled as described in `${CLAUDE_PLUGIN_ROOT}/rules/workflow.md` under "Autopilot operation"
4. End with the result block from `${CLAUDE_PLUGIN_ROOT}/rules/workflow.md`: `needs_input` if a question for the maintainer remains, otherwise `done`.
