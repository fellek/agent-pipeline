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

The pipeline rules are `${CLAUDE_PLUGIN_ROOT}/rules/workflow.md`; read the file only if the project's `CLAUDE.md` import has not already loaded it into your context.

Maintainer answer to an earlier open question (empty if none): $1

Failure summary of the previous attempt (empty if none): $2
If set, check that cause first and do not repeat the same approach.

1. Read the issue with `issue-text.py $0`, which prints only the text you may read; do not read the issue or its comments any other way. If it exits non-zero, end with `STATUS: blocked` and its message as `SUMMARY`.
2. Read the affected code.
3. Post one issue comment with:
   - approach in a few sentences
   - affected files
   - tests to add or change
   - for architecture decisions: 2 to 3 options with pros and cons and a recommendation
   - open questions, handled as described in the pipeline rules under "Autopilot steps"
4. End with the result block of the pipeline rules: `needs_input` if a question for the maintainer remains, otherwise `done`.
