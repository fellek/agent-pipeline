---
description: Check one GitHub issue without a status label and decide whether it is ready for the pipeline
argument-hint: <issue-number> [maintainer-answer] [failure-summary]
context: fork
agent: reviewer
background: true
model: opus
effort: medium
---

Check issue #$0 before the pipeline selects it. Do not change any files.

Maintainer answer to an earlier open question (empty if none): $1

Failure summary of the previous attempt (empty if none): $2
If set, check that cause first and do not repeat the same approach; do not post the analysis comment twice.

1. Read the issue and all its comments.
2. Kind: is it a bug, an improvement or an exception to a rule?
3. Effect: does it make the project better or more complicated?
4. Definition of Ready: acceptance criteria testable, no open questions, scope fits into one PR (otherwise sub-issues). Ignore blockers; the poller skips them via the GitHub dependencies.
5. Search the answer to every question first, in closed and open issues and pull requests (`gh issue list --state all --search <terms>`, `gh pr list --state all --search <terms>`), `docs/decisions/`, `docs/` and `CLAUDE.md`. Ask only what remains open.
6. Post one brief issue comment, for example `setprio: Verbesserung, macht das Projekt einfacher. Definition of Ready erfüllt: ready.`
7. Add the label `bug` for a bug or `enhancement` for an improvement. Set no status label; the orchestrator does.
8. End with the result block from CLAUDE.md:
   - `done` if it is a bug or an improvement that makes the project better and the Definition of Ready is met.
   - `needs_input` if it is an exception to a rule or makes the project more complicated: `OPEN_QUESTIONS` holds the reasoning and a proposal how to simplify or generalize the rule.
   - `needs_input` if the Definition of Ready is not met: `OPEN_QUESTIONS` holds the numbered questions.
