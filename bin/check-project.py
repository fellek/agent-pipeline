#!/usr/bin/env python3
"""Check the project in the working directory against the pipeline's requirements.

Fails if .claude/settings.json lacks a deny rule of the pipeline's settings
template or CLAUDE.md lacks the import of the pipeline's workflow rules.

Usage:
  check-project.py
"""

import json
import sys
from pathlib import Path

TEMPLATE = (
    Path(__file__).resolve().parents[1] / "templates" / "claude" / "settings.json"
)
SETTINGS = Path(".claude/settings.json")
CLAUDE_MD = Path("CLAUDE.md")
RULES_IMPORT = "@.claude/skills/pipeline/rules/workflow.md"


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


def claude_md_problems():
    lines = CLAUDE_MD.read_text().splitlines() if CLAUDE_MD.is_file() else []
    if RULES_IMPORT in (line.strip() for line in lines):
        return []
    return [f"{CLAUDE_MD} lacks the line {RULES_IMPORT}"]


def main(argv):
    if argv:
        sys.exit(__doc__)
    problems = settings_problems() + claude_md_problems()
    if problems:
        sys.exit("\n".join(problems))


if __name__ == "__main__":
    main(sys.argv[1:])
