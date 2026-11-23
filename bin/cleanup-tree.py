#!/usr/bin/env python3
"""Commit a modified working tree onto a new cleanup branch, without pushing.

Prints the name of the cleanup branch and switches back to the original
branch, or prints `clean` (exit 1) if there is nothing to commit.

Usage:
  cleanup-tree.py <issue>
"""

import datetime
import subprocess
import sys


def git(*args):
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def cleanup(issue):
    if not git("status", "--porcelain"):
        return None
    original = git("branch", "--show-current")
    timestamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    branch = f"cleanup/{issue}-{timestamp}"
    git("switch", "-c", branch)
    git("add", "-A")
    git("commit", "-m", f"Cleanup working tree of #{issue}")
    git("switch", original)
    return branch


def main(argv):
    if len(argv) != 1 or not argv[0].isdecimal():
        sys.exit(__doc__)
    branch = cleanup(argv[0])
    print(branch or "clean")
    if branch is None:
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
