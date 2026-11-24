# CLAUDE.md

@skills/pipeline/rules/workflow.md

## Coding style

- YAGNI: build what the issue asks for. No options, abstractions or extension points without a current use.
- Comments explain why, not what. No comments that repeat the code, no commented-out code.
- No em dashes, in code, comments, docs and commit messages.
- Docs are brief: what a reader needs to use or change the code, nothing the code already says.
- Read the documentation of a framework or library for the version in use before relying on a feature of it.

## Project

- This repository is the pipeline, a Claude Code plugin; projects include it as a submodule at `.claude/skills/pipeline` ([docs/autopilot.md](../docs/autopilot.md)).
- A finding about the pipeline made here is an ordinary `followup` issue in this repository.
- Nothing about a specific project goes into this repository: no names, paths, issues or other facts of a project.
