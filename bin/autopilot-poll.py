#!/usr/bin/env python3
"""Wait for maintainer input on GitHub; print it as JSON lines and exit.

Usage:
  autopilot-poll.py now
  autopilot-poll.py wait answer <issue> <since>
  autopilot-poll.py wait new_issue <label>
  autopilot-poll.py wait patch <branch> <head-sha>
"""

import json
import subprocess
import sys
import time
from email.utils import parsedate_to_datetime
from urllib.parse import quote

INTERVAL_SECONDS = 60
MAX_FAILED_POLLS = 3
SKIPPED_LABELS = {"blocked", "needs-info", "needs-human"}


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


def labeled_issues(issues):
    return [
        {"type": "labeled_issue", "number": i["number"], "title": i["title"]}
        for i in issues
        if "pull_request" not in i
        and not SKIPPED_LABELS & {label["name"] for label in i["labels"]}
    ]


def branch_head(branch):
    return gh_api(
        f"repos/{{owner}}/{{repo}}/branches/{branch}", "--jq", ".commit.sha"
    ).strip()


def new_commit(branch, head):
    current = branch_head(branch)
    if current == head:
        return []
    return [{"type": "commit", "branch": branch, "sha": current}]


def poll(mode, *args):
    if mode == "new_issue":
        (label,) = args
        path = f"repos/{{owner}}/{{repo}}/issues?state=open&labels={quote(label)}"
        return labeled_issues(gh(path))
    if mode == "patch":
        return new_commit(*args)
    number, since = args
    repo = "repos/{owner}/{repo}"
    comments = gh(f"{repo}/issues/comments?since={since}&per_page=100")
    on_number = [c for c in comments if c["issue_url"].endswith(f"/issues/{number}")]
    return owner_events(on_number, number, since)


def wait(mode, *args, sleep=time.sleep):
    failed_polls = 0
    while True:
        try:
            events = poll(mode, *args)
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
        case ["wait", "new_issue", label]:
            wait("new_issue", label)
        case ["wait", "answer", number, since]:
            wait("answer", int(number), since)
        case ["wait", "patch", branch, head]:
            wait("patch", branch, head)
        case _:
            sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
