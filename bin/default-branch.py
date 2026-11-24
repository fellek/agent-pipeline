#!/usr/bin/env python3
"""Print the default branch of origin, read from origin/HEAD.

If origin/HEAD is not set, it is set from the remote first.

Usage:
  default-branch.py
"""

import subprocess
import sys

ORIGIN_HEAD = "refs/remotes/origin/HEAD"


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False)


def origin_head():
    ref = git("symbolic-ref", "--quiet", "--short", ORIGIN_HEAD)
    return ref.stdout.strip().removeprefix("origin/") if ref.returncode == 0 else None


def default_branch():
    if branch := origin_head():
        return branch
    git("remote", "set-head", "origin", "--auto")
    return origin_head()


def main(argv):
    if argv:
        sys.exit(__doc__)
    branch = default_branch()
    if branch is None:
        sys.exit("origin/HEAD is not set: git remote set-head origin --auto failed")
    print(branch)


if __name__ == "__main__":
    main(sys.argv[1:])
