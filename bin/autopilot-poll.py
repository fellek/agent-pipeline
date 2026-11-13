#!/usr/bin/env python3
"""Wait for maintainer input on GitHub; print it as JSON lines and exit.

Usage:
  autopilot-poll.py now
  autopilot-poll.py wait answer <issue> <since>
  autopilot-poll.py wait new_issue
"""

import json
import subprocess
import sys
import time
from email.utils import parsedate_to_datetime

INTERVAL_SECONDS = 60
MAX_FAILED_POLLS = 3


def gh_api(*args):
    return subprocess.run(
        ["gh", "api", *args], capture_output=True, text=True, check=True
    ).stdout


def gh(path):
    pages = json.loads(gh_api("--paginate", "--slurp", path))
    return [item for page in pages for item in page]


def github_now():
    for line in gh_api("--include", "rate_limit").splitlines():
        if line.lower().startswith("date:"):
            moment = parsedate_to_datetime(line.split(":", 1)[1].strip())
            return moment.strftime("%Y-%m-%dT%H:%M:%SZ")
    raise RuntimeError("GitHub response has no Date header")


def owner_events(items, number, since):
    return [
        {
            "type": "comment",
            "number": number,
            "url": item["html_url"],
            "created_at": item["created_at"],
            "body": item["body"],
        }
        for item in items
        if item["author_association"] == "OWNER" and item["created_at"] > since
    ]


def ready_issues(issues):
    return [
        {"type": "ready_issue", "number": i["number"], "title": i["title"]}
        for i in issues
        if "pull_request" not in i
    ]


def poll(mode, number, since):
    if mode == "new_issue":
        return ready_issues(gh("repos/{owner}/{repo}/issues?state=open&labels=ready"))
    repo = "repos/{owner}/{repo}"
    comments = gh(f"{repo}/issues/comments?since={since}&per_page=100")
    on_number = [c for c in comments if c["issue_url"].endswith(f"/issues/{number}")]
    return owner_events(on_number, number, since)


def wait(mode, number, since, sleep=time.sleep):
    failed_polls = 0
    while True:
        try:
            events = poll(mode, number, since)
            failed_polls = 0
        except subprocess.CalledProcessError:
            failed_polls += 1
            if failed_polls == MAX_FAILED_POLLS:
                raise
            events = []
        if events:
            break
        sleep(INTERVAL_SECONDS)
    for event in events:
        print(json.dumps(event, ensure_ascii=False))


def main(argv):
    match argv:
        case ["now"]:
            print(github_now())
        case ["wait", "new_issue"]:
            wait("new_issue", None, None)
        case ["wait", "answer", number, since]:
            wait("answer", int(number), since)
        case _:
            sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
