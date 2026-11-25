#!/usr/bin/env python3
"""Print the state and open pull request of an issue as JSON.

Usage:
  issue-pr.py <issue>

Prints {"state", "pr", "branch", "review_rounds"}; pr and branch are null
without an open pull request that closes the issue. review_rounds counts the
changes requested reviews of the gate: a trusted author and an attestation line
for the pull request. The session lacks the key, so the MAC is not checked.
"""

import json
import subprocess
import sys

import attestation
from trust import TRUSTED


def gh(*args):
    return json.loads(
        subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout
    )


def gate_changes_requested(review, pr):
    if review["authorAssociation"] not in TRUSTED:
        return False
    return any(
        int(found_pr) == pr and verdict == attestation.CHANGES_REQUESTED
        for found_pr, _, verdict, _, _ in attestation.LINE.findall(review["body"])
    )


def find(issue):
    state = gh("issue", "view", issue, "--json", "state")["state"]
    prs = gh(
        "pr",
        "list",
        "--state",
        "open",
        "--limit",
        "200",
        "--json",
        "number,headRefName,closingIssuesReferences,reviews",
    )
    for pr in prs:
        if any(str(ref["number"]) == issue for ref in pr["closingIssuesReferences"]):
            rounds = sum(gate_changes_requested(r, pr["number"]) for r in pr["reviews"])
            return {
                "state": state,
                "pr": pr["number"],
                "branch": pr["headRefName"],
                "review_rounds": rounds,
            }
    return {"state": state, "pr": None, "branch": None, "review_rounds": 0}


def main(argv):
    match argv:
        case [issue] if issue.isdecimal():
            print(json.dumps(find(issue)))
        case _:
            sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
