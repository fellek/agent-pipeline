#!/usr/bin/env python3
"""Wait for the CI run at a commit and report its result.

Prints `green`, `red <run url>` or `missing`; exits 1 unless green.

Usage:
  watch-ci.py <branch> <sha>
"""

import json
import subprocess
import sys
import time

ATTEMPTS = 5
INTERVAL_SECONDS = 30


def find_run(branch, sha):
    for attempt in range(ATTEMPTS):
        if attempt:
            time.sleep(INTERVAL_SECONDS)
        runs = json.loads(
            subprocess.run(
                [
                    "gh",
                    "run",
                    "list",
                    "--workflow",
                    "CI",
                    "--branch",
                    branch,
                    "--commit",
                    sha,
                    "--json",
                    "databaseId,url",
                ],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        )
        if runs:
            return runs[0]
    return None


def watch(branch, sha):
    run = find_run(branch, sha)
    if run is None:
        return "missing"
    watched = subprocess.run(
        ["gh", "run", "watch", str(run["databaseId"]), "--exit-status"],
        stdout=subprocess.DEVNULL,
        check=False,
    )
    return "green" if watched.returncode == 0 else f"red {run['url']}"


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
