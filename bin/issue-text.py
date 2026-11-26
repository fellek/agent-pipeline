#!/usr/bin/env python3
"""Print an issue as JSON with only the text a fork may read.

Prints {"number", "title", "body", "comments"} with the comments of the owner,
members and collaborators. A stranger's issue is printed only while trust.approved
holds; otherwise it exits 1, and a writer has to label it again.

Usage:
  issue-text.py <issue>
"""

import json
import subprocess
import sys
from urllib.parse import quote

import trust


def gh(*args):
    return subprocess.run(
        ["gh", "api", *args], capture_output=True, text=True, check=True
    ).stdout


def pages(path):
    return [
        item for page in json.loads(gh("--paginate", "--slurp", path)) for item in page
    ]


def permission(login):
    try:
        answer = gh(f"repos/{{owner}}/{{repo}}/collaborators/{quote(login)}/permission")
    except subprocess.CalledProcessError:
        # A bot or app that is no collaborator gets 404.
        return None
    return json.loads(answer)["permission"]


def last_edited(number):
    return gh(
        "graphql",
        "-F",
        "owner={owner}",
        "-F",
        "repo={repo}",
        "-F",
        f"n={number}",
        "-f",
        f"query={trust.EDITED_QUERY}",
        "--jq",
        ".data.repository.issue.lastEditedAt",
    ).strip()


def issue_text(number):
    issue = json.loads(gh(f"repos/{{owner}}/{{repo}}/issues/{number}"))
    if issue["author_association"] not in trust.TRUSTED:
        events = pages(f"repos/{{owner}}/{{repo}}/issues/{number}/events?per_page=100")
        if not trust.approved(events, last_edited(number), permission):
            return None
    comments = pages(f"repos/{{owner}}/{{repo}}/issues/{number}/comments?per_page=100")
    return {
        "number": issue["number"],
        "title": issue["title"],
        "body": issue["body"],
        "comments": [
            {"author": c["user"]["login"], "body": c["body"]}
            for c in trust.trusted_comments(comments, "author_association")
        ],
    }


def gh_failed(error):
    # Without gh's stderr the step sees only an exit status, e.g. not the sandbox's
    # sudo error.
    sys.exit(f"gh failed: {(error.stderr or '').strip() or error}")


def main(argv):
    match argv:
        case [number] if number.isdigit():
            try:
                text = issue_text(number)
            except subprocess.CalledProcessError as error:
                gh_failed(error)
            if text is None:
                sys.exit(
                    f"#{number} is a stranger's issue, changed after the latest label "
                    "of a writer: label it again after reading it"
                )
            print(json.dumps(text, ensure_ascii=False))
        case _:
            sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
