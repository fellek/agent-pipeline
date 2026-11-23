#!/usr/bin/env python3
"""Merge origin/master into the current branch without pushing.

Prints `current`, `merged` or `conflict`; exits 1 on conflict.

Usage:
  merge-master.py
"""

import subprocess
import sys


def git(*args, check=True):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=check)


def succeeds(*args):
    return git(*args, check=False).returncode == 0


def merge_master():
    git("fetch", "origin", "master")
    if succeeds("merge-base", "--is-ancestor", "origin/master", "HEAD"):
        return "current"
    if succeeds("merge", "--no-edit", "origin/master"):
        return "merged"
    git("merge", "--abort")
    return "conflict"


def main(argv):
    if argv:
        sys.exit(__doc__)
    result = merge_master()
    print(result)
    if result == "conflict":
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
