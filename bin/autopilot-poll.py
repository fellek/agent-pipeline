#!/usr/bin/env python3
"""Poll GitHub for maintainer input on one or more targets; print it as JSON lines.

`wait` polls until a target has an event, `check` polls once. `next` prints the
issue to start: open issues with an open blocker are skipped, issues blocking an
open issue come first, then the lowest number. `untriaged` prints the open
issues without a status label and without the selection label, for `setprio`.

Usage:
  autopilot-poll.py now
  autopilot-poll.py next <label>
  autopilot-poll.py untriaged <label>
  autopilot-poll.py wait|check <target>...

Targets:
  answer <issue> <since>
  new_issue <label>
  patch <branch> <head-sha>
"""

import json
import subprocess
import sys
import time
from email.utils import parsedate_to_datetime
from urllib.parse import quote

INTERVAL_SECONDS = 60
MAX_FAILED_POLLS = 3
SKIPPED_LABELS = {"question", "parked"}
STATUS_LABELS = SKIPPED_LABELS | {"ready", "in-progress", "in-review", "approved"}
TARGET_ARITY = {"answer": 2, "new_issue": 1, "patch": 2}


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


def dependencies(number, relation):
    return gh(f"repos/{{owner}}/{{repo}}/issues/{number}/dependencies/{relation}")


def has_open(number, relation):
    return any(issue["state"] == "open" for issue in dependencies(number, relation))


def label_names(issue):
    return [label["name"] for label in issue["labels"]]


def summary(issue):
    return {
        "number": issue["number"],
        "title": issue["title"],
        "labels": label_names(issue),
    }


def candidates(label):
    issues = gh(f"repos/{{owner}}/{{repo}}/issues?state=open&labels={quote(label)}")
    return [
        summary(i)
        for i in issues
        if "pull_request" not in i
        and not SKIPPED_LABELS & set(label_names(i))
        and not has_open(i["number"], "blocked_by")
    ]


def untriaged(label):
    issues = gh("repos/{owner}/{repo}/issues?state=open")
    excluded = STATUS_LABELS | {label}
    return [
        summary(i)
        for i in issues
        if "pull_request" not in i and not excluded & set(label_names(i))
    ]


def priority(issue):
    return not has_open(issue["number"], "blocking"), issue["number"]


def next_issue(label):
    issues = candidates(label)
    if issues:
        print_events([min(issues, key=priority)])


def branch_head(branch):
    return gh_api(
        f"repos/{{owner}}/{{repo}}/branches/{branch}", "--jq", ".commit.sha"
    ).strip()


def new_commit(branch, head):
    current = branch_head(branch)
    if current == head:
        return []
    return [{"type": "commit", "branch": branch, "sha": current}]


def answers(cursors):
    since = min(since for _, since in cursors)
    comments = gh(
        f"repos/{{owner}}/{{repo}}/issues/comments?since={since}&per_page=100"
    )
    events = []
    for number, since in cursors:
        on_number = [
            c for c in comments if c["issue_url"].endswith(f"/issues/{number}")
        ]
        events += owner_events(on_number, number, since)
    return events


def poll(targets):
    cursors = [args for mode, *args in targets if mode == "answer"]
    events = answers(cursors) if cursors else []
    for mode, *args in targets:
        if mode == "new_issue":
            events += [{"type": "labeled_issue", **i} for i in candidates(*args)]
            events += [{"type": "untriaged_issue", **i} for i in untriaged(*args)]
        elif mode == "patch":
            events += new_commit(*args)
    return events


def print_events(events):
    for event in events:
        print(json.dumps(event, ensure_ascii=False))


def wait(targets, sleep=time.sleep):
    failed_polls = 0
    while True:
        try:
            events = poll(targets)
            failed_polls = 0
        except subprocess.CalledProcessError:
            failed_polls += 1
            if failed_polls == MAX_FAILED_POLLS:
                raise
            events = []
        if events:
            break
        sleep(INTERVAL_SECONDS)
    print_events(events)


def check(targets):
    print_events(poll(targets))


def parse_targets(args):
    targets = []
    while args:
        mode, *rest = args
        arity = TARGET_ARITY.get(mode)
        if arity is None or len(rest) < arity:
            raise ValueError(args)
        params, args = rest[:arity], rest[arity:]
        if mode == "answer":
            params[0] = int(params[0])
        targets.append((mode, *params))
    if not targets:
        raise ValueError(args)
    return targets


def main(argv):
    match argv:
        case ["now"]:
            print(github_now())
        case ["next", label]:
            next_issue(label)
        case ["untriaged", label]:
            print_events(untriaged(label))
        case ["wait" | "check" as command, *args]:
            try:
                targets = parse_targets(args)
            except ValueError:
                sys.exit(__doc__)
            {"wait": wait, "check": check}[command](targets)
        case _:
            sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
