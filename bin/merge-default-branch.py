#!/usr/bin/env python3
"""Merge the default branch of origin into the current branch without pushing.

Prints `current`, `merged` or `conflict`; exits 1 on conflict. If the default
branch cannot be determined, prints the error of default-branch.py to stderr and
exits 2.

Usage:
  merge-default-branch.py
"""

import subprocess
import sys
from pathlib import Path

DEFAULT_BRANCH = Path(__file__).resolve().with_name("default-branch.py")


def git(*args, check=True):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=check)


def succeeds(*args):
    return git(*args, check=False).returncode == 0


def default_branch():
    result = subprocess.run(
        [DEFAULT_BRANCH], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        print(result.stderr.strip(), file=sys.stderr)
        sys.exit(2)
    return result.stdout.strip()


def merge_default_branch():
    branch = default_branch()
    upstream = f"origin/{branch}"
    git("fetch", "origin", branch)
    if succeeds("merge-base", "--is-ancestor", upstream, "HEAD"):
        return "current"
    if succeeds("merge", "--no-edit", upstream):
        return "merged"
    git("merge", "--abort")
    return "conflict"


def main(argv):
    if argv:
        sys.exit(__doc__)
    result = merge_default_branch()
    print(result)
    if result == "conflict":
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
