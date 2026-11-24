#!/usr/bin/env python3
"""Merge the default branch of origin into the current branch without pushing.

Prints `current`, `merged` or `conflict`; exits 1 on conflict. Any other failure
(the default branch cannot be determined, the fetch fails, or the merge does not
start, e.g. because it would overwrite an untracked file) prints the error to
stderr and exits 2, with nothing on stdout.

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


def fail(message):
    print(message.strip(), file=sys.stderr)
    sys.exit(2)


def default_branch():
    result = subprocess.run(
        [DEFAULT_BRANCH], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        fail(result.stderr)
    return result.stdout.strip()


def merge_default_branch():
    branch = default_branch()
    upstream = f"origin/{branch}"
    git("fetch", "origin", branch)
    if succeeds("merge-base", "--is-ancestor", upstream, "HEAD"):
        return "current"
    merge = git("merge", "--no-edit", upstream, check=False)
    if merge.returncode == 0:
        return "merged"
    if not succeeds("rev-parse", "--verify", "--quiet", "MERGE_HEAD"):
        fail(merge.stderr or merge.stdout)
    git("merge", "--abort")
    return "conflict"


def main(argv):
    if argv:
        sys.exit(__doc__)
    try:
        result = merge_default_branch()
    except subprocess.CalledProcessError as error:
        fail(error.stderr or str(error))
    print(result)
    if result == "conflict":
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
