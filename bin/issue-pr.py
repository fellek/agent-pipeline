#!/usr/bin/env python3
"""Print the state and open pull request of an issue as JSON.

Usage:
  issue-pr.py <issue>

Prints {"state", "pr", "branch", "review_rounds"}; pr and branch are null
without an open pull request that closes the issue.
"""

import json
import subprocess
import sys

CHANGES_REQUESTED = "Verdict: changes requested"


def gh(*args):
    return json.loads(
        subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout
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
            rounds = sum(
                review["body"].startswith(CHANGES_REQUESTED) for review in pr["reviews"]
            )
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
