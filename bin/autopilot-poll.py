#!/usr/bin/env python3
"""Poll GitHub for maintainer input on one or more targets; print it as JSON lines.

`wait` polls until a target has an event, `check` polls once. `next` prints the
issue to start: open issues with an open blocker are skipped, issues blocking an
open issue come first, then the lowest number. `untriaged` prints the open
issues without a status label and without the selection label, for `setprio`.

Only issues of the repository's owner, members and collaborators enter the
pipeline, so a stranger's issue cannot steer a fork. A stranger's issue becomes a
candidate only once someone with write access gives it the selection label
(trust.py); forks read an issue only through issue-text.py.

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

import functools
import json
import subprocess
import sys
import time
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import trust

INTERVAL_SECONDS = 60
MAX_FAILED_POLLS = 3
SKIPPED_LABELS = {"question", "parked"}
STATUS_LABELS = trust.STATUS_LABELS
TRUSTED = trust.TRUSTED
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


@functools.cache
def maintainer():
    """The login of the token: the maintainer, in an organization a MEMBER."""
    return gh_api("user", "--jq", ".login").strip()


def maintainer_events(items, number, since):
    # Comments of the pipeline carry the gate's marker; they are no answers.
    return [
        {
            "type": "comment",
            "number": number,
            "url": item["html_url"],
            "created_at": item["created_at"],
            "body": item["body"],
        }
        for item in items
        if item["user"]["login"] == maintainer()
        and trust.MARKER not in item["body"]
        and item["created_at"] > since
    ]


def has_open(issue, relation):
    # The issue list counts the open dependencies, which saves a call per issue.
    return issue["issue_dependencies_summary"][relation] > 0


def label_names(issue):
    return [label["name"] for label in issue["labels"]]


def summary(issue):
    return {
        "number": issue["number"],
        "title": issue["title"],
        "labels": label_names(issue),
    }


def permission(login):
    try:
        answer = gh_api(
            f"repos/{{owner}}/{{repo}}/collaborators/{quote(login)}/permission"
        )
    except subprocess.CalledProcessError:
        # A bot or app that is no collaborator gets 404.
        return None
    return json.loads(answer)["permission"]


def labeled_by_writer(number, label):
    events = gh(f"repos/{{owner}}/{{repo}}/issues/{number}/events?per_page=100")
    edited = gh_api(
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
    return trust.approved(events, edited, permission, label)


def trusted(issue, label):
    return issue["author_association"] in TRUSTED or labeled_by_writer(
        issue["number"], label
    )


def open_issues():
    issues = gh("repos/{owner}/{repo}/issues?state=open&per_page=100")
    return sorted(
        (i for i in issues if "pull_request" not in i), key=lambda i: i["number"]
    )


def candidates(label, issues):
    """The startable issues, lowest number first; lazy, because a stranger's
    issue costs calls for its label events."""
    return (
        i
        for i in issues
        if label in label_names(i)
        and not SKIPPED_LABELS & set(label_names(i))
        and not has_open(i, "blocked_by")
        and trusted(i, label)
    )


def untriaged(label, issues):
    excluded = STATUS_LABELS | {label}
    return [
        summary(i)
        for i in issues
        if i["author_association"] in TRUSTED and not excluded & set(label_names(i))
    ]


def priority(issue):
    return not has_open(issue, "blocking"), issue["number"]


def next_issue(label):
    issues = list(candidates(label, open_issues()))
    if issues:
        print_events([summary(min(issues, key=priority))])


def branch_head(branch):
    return gh_api(
        f"repos/{{owner}}/{{repo}}/branches/{branch}", "--jq", ".commit.sha"
    ).strip()


def new_commit(branch, head):
    current = branch_head(branch)
    if current == head:
        return []
    return [{"type": "commit", "branch": branch, "sha": current}]


def answers(number, since):
    # Per issue, so an old cursor costs pages of that issue only.
    comments = gh(
        f"repos/{{owner}}/{{repo}}/issues/{number}/comments?since={since}&per_page=100"
    )
    return maintainer_events(comments, number, since)


def poll(targets):
    """The events of the targets. One startable issue is enough to wake the
    orchestrator, so the search stops at the first."""
    events = []
    for mode, *args in targets:
        if mode == "answer":
            events += answers(*args)
        elif mode == "new_issue":
            (label,) = args
            issues = open_issues()
            if first := next(candidates(label, issues), None):
                events.append({"type": "labeled_issue", **summary(first)})
            events += [
                {"type": "untriaged_issue", **i} for i in untriaged(label, issues)
            ]
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
            print_events(untriaged(label, open_issues()))
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
