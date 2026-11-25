#!/usr/bin/env python3
"""Post the plan of an issue from a file, or edit the plan comment a rerun left.

The plan comment starts with PLAN. A trusted comment with PLAN and trust.MARKER
(which the gate appends) is the pipeline's own; the latest one is edited, so a
rerun leaves one plan on the issue. Prints the comment's URL. The plan comes in
a file, as text on stdin would keep the call in the sandbox (gh-shim.py).

Usage:
  post-plan.py <issue> <file>
"""

import json
import subprocess
import sys
from pathlib import Path

import trust

PLAN = "<!-- pipeline:plan -->"


def gh(*args, input=None):
    return subprocess.run(
        ["gh", "api", *args], input=input, capture_output=True, text=True, check=True
    ).stdout


def plan_comment(number):
    comments = [
        c
        for page in json.loads(
            gh(
                "--paginate",
                "--slurp",
                f"repos/{{owner}}/{{repo}}/issues/{number}/comments?per_page=100",
            )
        )
        for c in page
    ]
    own = [
        c
        for c in trust.trusted_comments(comments, "author_association")
        if c["body"].startswith(PLAN) and trust.MARKER in c["body"]
    ]
    return own[-1]["id"] if own else None


def main(argv):
    if len(argv) != 2 or not argv[0].isdigit():
        sys.exit(__doc__)
    number, path = argv
    body = json.dumps({"body": f"{PLAN}\n{Path(path).read_text().strip()}"})
    found = plan_comment(number)
    if found is None:
        args = (
            "--method",
            "POST",
            f"repos/{{owner}}/{{repo}}/issues/{number}/comments",
        )
    else:
        args = (
            "--method",
            "PATCH",
            f"repos/{{owner}}/{{repo}}/issues/comments/{found}",
        )
    print(json.loads(gh(*args, "--input", "-", input=body))["html_url"])


if __name__ == "__main__":
    main(sys.argv[1:])
