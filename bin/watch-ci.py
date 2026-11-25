#!/usr/bin/env python3
"""Wait for the CI runs at a commit and report their result.

On a pull request branch it waits until a run of every workflow under
"Required workflows:" in the "## Checks" section of .claude/rules/project.md has
started, so a late workflow is not missed; on the default branch, where a
workflow may run only for pull requests, it takes the runs it finds. The review
workflows are left out: they depend on the review, not on the code.

Prints `green`, `red <run url>` of the first failed run, `missing` (after
2 minutes without the runs) or, after an overall deadline of 45 minutes,
`timeout`; exits 1 unless green. The orchestrator runs it in the background,
so the deadline only bounds a run that never ends.

Usage:
  watch-ci.py <branch> <sha>
"""

import json
import re
import subprocess
import sys
import time
from pathlib import Path

import attestation

ATTEMPTS = 5
INTERVAL_SECONDS = 30
DEADLINE_SECONDS = 45 * 60
PROJECT_RULES = Path(".claude/rules/project.md")
DEFAULT_BRANCH = Path(__file__).resolve().with_name("default-branch.py")
REQUIRED = re.compile(r"^Required workflows:(.*)$", re.MULTILINE)


def required_workflows(text):
    """The names under "Required workflows:" in the "## Checks" section."""
    section = re.search(
        r"^## Checks[ \t]*\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL
    )
    match = REQUIRED.search(section.group(1)) if section else None
    return [name.strip() for name in match.group(1).split(",")] if match else []


def latest_runs(branch, sha):
    """The latest run of each workflow at the commit, newest first from gh."""
    runs = json.loads(
        subprocess.run(
            [
                "gh",
                "run",
                "list",
                "--branch",
                branch,
                "--commit",
                sha,
                "--limit",
                "100",
                "--json",
                "databaseId,name,url",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    latest = {}
    for run in runs:
        if run["name"] not in attestation.REVIEW_WORKFLOWS:
            latest.setdefault(run["name"], run)
    return latest


def find_runs(branch, sha, required):
    for attempt in range(ATTEMPTS):
        if attempt:
            time.sleep(INTERVAL_SECONDS)
        runs = latest_runs(branch, sha)
        if runs and all(name in runs for name in required):
            return runs
    return None


def result_of(run, deadline):
    watched = subprocess.run(
        ["gh", "run", "watch", str(run["databaseId"]), "--exit-status"],
        stdout=subprocess.DEVNULL,
        check=False,
        timeout=max(0, deadline - time.monotonic()),
    )
    return "green" if watched.returncode == 0 else f"red {run['url']}"


def default_branch():
    return subprocess.run(
        [DEFAULT_BRANCH], capture_output=True, text=True, check=True
    ).stdout.strip()


def watch(branch, sha):
    deadline = time.monotonic() + DEADLINE_SECONDS
    required = []
    if branch != default_branch() and PROJECT_RULES.is_file():
        required = required_workflows(PROJECT_RULES.read_text())
    try:
        runs = find_runs(branch, sha, required)
        if runs is None:
            return "missing"
        for run in runs.values():
            if (result := result_of(run, deadline)) != "green":
                return result
        return "green"
    except subprocess.TimeoutExpired:
        return "timeout"


def main(argv):
    match argv:
        case [branch, sha]:
            result = watch(branch, sha)
            print(result)
            if result != "green":
                sys.exit(1)
        case _:
            sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
