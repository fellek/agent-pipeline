#!/usr/bin/env python3
"""Check the project in the working directory against the pipeline's requirements.

Fails if .claude/settings.json lacks a deny rule of the pipeline's settings
template, or if neither CLAUDE.md nor .claude/CLAUDE.md imports the pipeline's
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


def deny_rules(path):
    return json.loads(path.read_text()).get("permissions", {}).get("deny", [])


def settings_problems():
    if not SETTINGS.is_file():
        return [f"{SETTINGS} is missing"]
    try:
        denied = set(deny_rules(SETTINGS))
    except json.JSONDecodeError as error:
        return [f"{SETTINGS} is no valid JSON: {error}"]
    return [
        f"{SETTINGS} lacks the deny rule {rule}"
        for rule in deny_rules(TEMPLATE)
        if rule not in denied
    ]


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
