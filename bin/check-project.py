#!/usr/bin/env python3
"""Check the project in the working directory against the pipeline's requirements.

Fails if .claude/settings.json lacks a deny rule, the SessionStart hook (it warns
about a missing or stale release), a switch of the Bash sandbox or a path the
sandbox may not read (the credentials) of the pipeline's settings template, or if neither CLAUDE.md nor .claude/CLAUDE.md imports the pipeline's
workflow rules: an @ line whose path, relative to the file it is in, points to
.claude/skills/pipeline/rules/workflow.md of the project. Only the path counts,
not whether the file exists, so the check passes without the release checked out.

Also fails for each command in the first code block under "## Checks" in
.claude/rules/project.md that a Bash deny rule matches or no Bash allow rule
does, since the autopilot would wait for an approval. Rules match as in Claude
Code: each subcommand of a compound command on its own, "*" stands for any text.
With checks, the section also needs a line "Required workflows: <name>, ..." whose
names are workflows in .github/workflows, the CI runs the autopilot waits for.

Usage:
  check-project.py
"""

import json
import os
import re
import sys
from pathlib import Path

TEMPLATE = (
    Path(__file__).resolve().parents[1] / "templates" / "claude" / "settings.json"
)
SETTINGS = Path(".claude/settings.json")
CLAUDE_MDS = (Path("CLAUDE.md"), Path(".claude/CLAUDE.md"))
RULES = ".claude/skills/pipeline/rules/workflow.md"
PROJECT_RULES = Path(".claude/rules/project.md")
WORKFLOWS = Path(".github/workflows")
# Quoted text is matched first so that separators in it are skipped; an & next to
# < or > is part of a redirection such as 2>&1 or &>.
SEPARATOR = re.compile(
    r"""'[^']*'|"(?:\\.|[^"\\])*"|(&&|\|\||\|&|[;|]|(?<![<>])&(?!>))"""
)


def deny_rules(settings):
    return settings.get("permissions", {}).get("deny", [])


def session_start_commands(settings):
    return [
        hook.get("command")
        for matcher in settings.get("hooks", {}).get("SessionStart", [])
        for hook in matcher.get("hooks", [])
    ]


def load_settings():
    """Return the settings and None, or None and the problem."""
    if not SETTINGS.is_file():
        return None, f"{SETTINGS} is missing"
    try:
        return json.loads(SETTINGS.read_text()), None
    except json.JSONDecodeError as error:
        return None, f"{SETTINGS} is no valid JSON: {error}"


def settings_problems(settings):
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
    sandbox = settings.get("sandbox", {})
    problems += [
        f"{SETTINGS} lacks sandbox.{key}: {json.dumps(value)}"
        for key, value in template["sandbox"].items()
        if isinstance(value, bool) and sandbox.get(key) != value
    ]
    denied_reads = sandbox.get("filesystem", {}).get("denyRead", [])
    problems += [
        f"{SETTINGS} lacks sandbox.filesystem.denyRead: {path}"
        for path in template["sandbox"]["filesystem"]["denyRead"]
        if path not in denied_reads
    ]
    return problems


def check_commands():
    if not PROJECT_RULES.is_file():
        return []
    match = re.search(
        r"^## Checks[ \t]*\n(?:(?!#)[^\n]*\n)*?```[^\n]*\n(.*?)^```",
        PROJECT_RULES.read_text(),
        re.MULTILINE | re.DOTALL,
    )
    if match is None:
        return []
    return [line.strip() for line in match.group(1).splitlines() if line.strip()]


def bash_patterns(rules):
    return [
        "*" if rule == "Bash" else rule[5:-1]
        for rule in rules
        if rule == "Bash" or (rule.startswith("Bash(") and rule.endswith(")"))
    ]


def matches(pattern, command):
    if pattern.endswith(":*"):
        pattern = pattern[:-2] + " *"
    regex = ".*".join(map(re.escape, pattern.split("*")))
    if re.fullmatch(regex, command, re.DOTALL):
        return True
    # A trailing " *" that is the only wildcard also matches the bare command.
    return (
        pattern.endswith(" *") and pattern.count("*") == 1 and command == pattern[:-2]
    )


def subcommands(command):
    parts, start = [], 0
    for match in SEPARATOR.finditer(command):
        if match.group(1):
            parts.append(command[start : match.start()])
            start = match.end()
    parts.append(command[start:])
    return [part.strip() for part in parts if part.strip()]


def check_command_problems(settings):
    allow = bash_patterns(settings.get("permissions", {}).get("allow", []))
    deny = bash_patterns(deny_rules(settings))
    problems = []
    for command in check_commands():
        parts = subcommands(command)
        if any(matches(p, part) for part in parts for p in deny):
            problems.append(f"{SETTINGS} denies the check command {command}")
        elif not all(any(matches(p, part) for p in allow) for part in parts):
            problems.append(f"{SETTINGS} does not allow the check command {command}")
    return problems


def workflow_problems():
    if not check_commands():
        return []
    section = re.search(
        r"^## Checks[ \t]*\n(.*?)(?=^## |\Z)",
        PROJECT_RULES.read_text(),
        re.MULTILINE | re.DOTALL,
    )
    match = re.search(r"^Required workflows:(.*)$", section.group(1), re.MULTILINE)
    names = [n.strip() for n in match.group(1).split(",") if n.strip()] if match else []
    if not names:
        return [f"{PROJECT_RULES} lacks a line Required workflows: <name>, ..."]
    known = {
        found.group(1).strip().strip("'\"")
        for path in [*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")]
        if (found := re.search(r"^name:(.*)$", path.read_text(), re.MULTILINE))
    }
    return [
        f"{PROJECT_RULES} requires the workflow {name}, which {WORKFLOWS} lacks"
        for name in names
        if name not in known
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
    settings, problem = load_settings()
    if settings is None:
        problems = [problem]
    else:
        problems = settings_problems(settings) + check_command_problems(settings)
    problems += claude_md_problems() + workflow_problems()
    if problems:
        sys.exit("\n".join(problems))


if __name__ == "__main__":
    main(sys.argv[1:])
