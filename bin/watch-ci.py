#!/usr/bin/env python3
"""Wait for the CI run at a commit and report its result.

A pull request commit also waits for its Integration run, if there is one.

Prints `green`, `red <run url>`, `missing` or, after an overall deadline of 45
minutes, `timeout`; exits 1 unless green. The orchestrator runs it in the
background, so the deadline only bounds a run that never ends.

Usage:
  watch-ci.py <branch> <sha>
"""

import json
import subprocess
import sys
import time

ATTEMPTS = 5
INTERVAL_SECONDS = 30
DEADLINE_SECONDS = 45 * 60


def list_runs(workflow, branch, sha, *extra):
    return json.loads(
        subprocess.run(
            [
                "gh",
                "run",
                "list",
                "--workflow",
                workflow,
                "--branch",
                branch,
                "--commit",
                sha,
                *extra,
                "--json",
                "databaseId,url",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )


def find_run(branch, sha):
    for attempt in range(ATTEMPTS):
        if attempt:
            time.sleep(INTERVAL_SECONDS)
        if runs := list_runs("CI", branch, sha):
            return runs[0]
    return None


def result_of(run, deadline):
    watched = subprocess.run(
        ["gh", "run", "watch", str(run["databaseId"]), "--exit-status"],
        stdout=subprocess.DEVNULL,
        check=False,
        timeout=max(0, deadline - time.monotonic()),
    )
    return "green" if watched.returncode == 0 else f"red {run['url']}"


def watch(branch, sha):
    deadline = time.monotonic() + DEADLINE_SECONDS
    try:
        run = find_run(branch, sha)
        if run is None:
            return "missing"
        result = result_of(run, deadline)
        if result != "green":
            return result
        integration = list_runs("Integration", branch, sha, "--event", "pull_request")
        return result_of(integration[0], deadline) if integration else result
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
