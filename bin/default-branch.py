#!/usr/bin/env python3
"""Print the default branch of origin, read from origin/HEAD.

If origin/HEAD is not set or points to a branch that no longer exists (after the
default branch was renamed and the clone pruned), it is set from the remote first.

Usage:
  default-branch.py
"""

import subprocess
import sys

ORIGIN_HEAD = "refs/remotes/origin/HEAD"


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False)


def origin_head():
    if git("rev-parse", "--verify", "--quiet", ORIGIN_HEAD).returncode != 0:
        return None
    # The full ref, since --short is ambiguous with a local branch named origin/<x>.
    ref = git("symbolic-ref", "--quiet", ORIGIN_HEAD)
    branch = ref.stdout.strip().removeprefix("refs/remotes/origin/")
    return branch if ref.returncode == 0 else None


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
