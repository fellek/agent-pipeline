#!/usr/bin/env python3
"""Fail unless the latest review on the head commit starts with `Verdict: approve`.

Usage:
  agent-review.py <pr> <head_sha>
"""

import json
import subprocess
import sys

APPROVE = "Verdict: approve"


def reviews(pr):
    pages = subprocess.run(
        [
            "gh",
            "api",
            "--paginate",
            "--slurp",
            f"repos/{{owner}}/{{repo}}/pulls/{pr}/reviews?per_page=100",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [review for page in json.loads(pages) for review in page]


def approved(reviews, head_sha):
    # Replies to inline threads create reviews with an empty body.
    verdicts = [
        r["body"].strip()
        for r in reviews
        if r["commit_id"] == head_sha
        and r["state"] != "DISMISSED"
        and r["body"].strip()
    ]
    return bool(verdicts) and verdicts[-1].splitlines()[0].strip() == APPROVE


def main(argv):
    match argv:
        case [pr, head_sha]:
            if not approved(reviews(pr), head_sha):
                sys.exit(f"No '{APPROVE}' review for {head_sha}")
        case _:
            sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
