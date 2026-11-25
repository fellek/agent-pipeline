#!/usr/bin/env python3
"""Print the unresolved review threads of a pull request as a JSON array.

Only threads opened by the repository's owner, members and collaborators count:
the reviewer and the maintainer. Threads of strangers neither block the merge nor
reach fix-review.

Usage:
  open-review-threads.py <pr>
"""

import json
import subprocess
import sys

TRUSTED = {"OWNER", "MEMBER", "COLLABORATOR"}

QUERY = """
query($owner: String!, $repo: String!, $pr: Int!, $endCursor: String) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $pr) {
      reviewThreads(first: 100, after: $endCursor) {
        pageInfo { hasNextPage endCursor }
        nodes { isResolved path line comments(first: 1) { nodes { url authorAssociation } } }
      }
    }
  }
}
"""


def threads(pr):
    pages = subprocess.run(
        [
            "gh",
            "api",
            "graphql",
            "--paginate",
            "--slurp",
            "-F",
            "owner={owner}",
            "-F",
            "repo={repo}",
            "-F",
            f"pr={pr}",
            "-f",
            f"query={QUERY}",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [
        thread
        for page in json.loads(pages)
        for thread in page["data"]["repository"]["pullRequest"]["reviewThreads"][
            "nodes"
        ]
    ]


def unresolved(threads):
    return [
        {
            "url": t["comments"]["nodes"][0]["url"],
            "path": t["path"],
            "line": t["line"],
        }
        for t in threads
        if not t["isResolved"]
        and t["comments"]["nodes"][0]["authorAssociation"] in TRUSTED
    ]


def main(argv):
    match argv:
        case [pr]:
            print(json.dumps(unresolved(threads(pr))))
        case _:
            sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
