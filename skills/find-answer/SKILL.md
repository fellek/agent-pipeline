---
description: Search the project for the answer to an open question of a GitHub issue without posting anything
argument-hint: <issue-number> <questions> [unused]
context: fork
agent: pipeline:reviewer
background: true
model: sonnet
effort: medium
---

Look for the answer to the open questions of issue #$0 in the project itself.

The pipeline rules are `${CLAUDE_PLUGIN_ROOT}/rules/workflow.md`; read the file only if the project's `CLAUDE.md` import has not already loaded it into your context.

Open questions: $1

1. Read the issue with `issue-text.py $0`, which prints only the text you may read; do not read the issue or its comments any other way. If it exits non-zero, end with `STATUS: blocked` and its message as `SUMMARY`.
2. Search closed and open issues and pull requests (`gh issue list --state all --search <terms>`, `gh pr list --state all --search <terms>`), `docs/decisions/`, `docs/` and `CLAUDE.md`.
3. Count an answer only if a project rule or a recorded maintainer decision settles every question. A guess or an option you merely prefer is no answer.
4. Post nothing and change no files. The orchestrator posts the result.
5. End with the result block of the pipeline rules: `STATUS: done` with the answer as one sentence and a source link in `SUMMARY` if every question is settled, otherwise `STATUS: needs_input`.
