#!/usr/bin/env python3
"""Check the project in the working directory against the pipeline's requirements.

Fails if .claude/settings.json lacks a deny rule or the SessionStart hook of the
pipeline's settings template (it warns about a missing or stale release), or if neither CLAUDE.md nor .claude/CLAUDE.md imports the pipeline's
workflow rules: an @ line whose path, relative to the file it is in, points to
.claude/skills/pipeline/rules/workflow.md of the project. Only the path counts,
not whether the file exists, so the check passes without the release checked out.

Usage:
  check-project.py
"""

import json
import os
import sys
from pathlib import Path

TEMPLATE = (
    Path(__file__).resolve().parents[1] / "templates" / "claude" / "settings.json"
)
SETTINGS = Path(".claude/settings.json")
CLAUDE_MDS = (Path("CLAUDE.md"), Path(".claude/CLAUDE.md"))
RULES = ".claude/skills/pipeline/rules/workflow.md"


def deny_rules(settings):
    return settings.get("permissions", {}).get("deny", [])


def session_start_commands(settings):
    return [
        hook.get("command")
        for matcher in settings.get("hooks", {}).get("SessionStart", [])
        for hook in matcher.get("hooks", [])
    ]


def settings_problems():
    if not SETTINGS.is_file():
        return [f"{SETTINGS} is missing"]
    try:
        settings = json.loads(SETTINGS.read_text())
    except json.JSONDecodeError as error:
        return [f"{SETTINGS} is no valid JSON: {error}"]
    template = json.loads(TEMPLATE.read_text())
    denied = set(deny_rules(settings))
    problems = [
        f"{SETTINGS} lacks the deny rule {rule}"
        for rule in deny_rules(template)
        if rule not in denied
    ]
    commands = session_start_commands(settings)
    problems += [
        f"{SETTINGS} lacks the SessionStart hook of the pipeline: {command}"
        for command in session_start_commands(template)
        if command not in commands
    ]
    return problems


def normalized(path):
    # normpath, not resolve: the release worktree may be a symlink or missing.
    return os.path.normpath(os.path.abspath(path))


def imports_rules(claude_md):
    if not claude_md.is_file():
        return False
    for line in claude_md.read_text().splitlines():
        line = line.strip()
        if line.startswith("@") and normalized(
            claude_md.parent / line[1:]
        ) == normalized(RULES):
            return True
    return False


def claude_md_problems():
    if any(imports_rules(path) for path in CLAUDE_MDS):
        return []
    names = " and ".join(str(path) for path in CLAUDE_MDS)
    return [f"{names} lack an import of {RULES}"]


def main(argv):
    if argv:
        sys.exit(__doc__)
    problems = settings_problems() + claude_md_problems()
    if problems:
        sys.exit("\n".join(problems))


if __name__ == "__main__":
    main(sys.argv[1:])
