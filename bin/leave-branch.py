#!/usr/bin/env python3
"""Check that a branch can be left and push its commits that are not on origin.

Prints `dirty` (exit 1) for a modified working tree, `pushed` or `clean`;
a failed fetch or push prints `push failed: <error>` (exit 2). Never pushes the
default branch.

Usage:
  leave-branch.py <branch>
"""

import subprocess
import sys
from pathlib import Path

DEFAULT_BRANCH = Path(__file__).resolve().with_name("default-branch.py")


def git(*args, check=False):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=check)


def default_branch():
    return subprocess.run(
        [DEFAULT_BRANCH], capture_output=True, text=True, check=True
    ).stdout.strip()


def has_unpushed_commits(branch):
    unpushed = git("rev-list", branch, "--not", "--remotes=origin", "--", check=True)
    return unpushed.stdout.strip() != ""


def leave(branch):
    if git("status", "--porcelain").stdout:
        return "dirty", 1
    if branch == default_branch():
        return "clean", 0
    fetch = git("fetch", "origin")
    if fetch.returncode != 0:
        return f"push failed: {fetch.stderr.strip()}", 2
    if not has_unpushed_commits(branch):
        return "clean", 0
    push = git("push", "origin", branch)
    if push.returncode != 0:
        return f"push failed: {push.stderr.strip()}", 2
    return "pushed", 0


def main(argv):
    if len(argv) != 1:
        sys.exit(__doc__)
    output, code = leave(argv[0])
    print(output)
    sys.exit(code)


if __name__ == "__main__":
    main(sys.argv[1:])
