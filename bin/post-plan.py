#!/usr/bin/env python3
"""Post the plan of an issue from stdin, or edit the plan comment a rerun left.

The plan comment starts with PLAN. A trusted comment with PLAN and trust.MARKER
(which the gate appends) is the pipeline's own; the latest one is edited, so a
rerun leaves one plan on the issue. Prints the comment's URL.

Usage:
  post-plan.py <issue> < plan
"""

import json
import subprocess
import sys

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
    if len(argv) != 1 or not argv[0].isdigit():
        sys.exit(__doc__)
    number = argv[0]
    body = json.dumps({"body": f"{PLAN}\n{sys.stdin.read().strip()}"})
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
