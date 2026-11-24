#!/usr/bin/env python3
"""Check that the latest review on the head commit starts with `Verdict: approve`.

Without `sync` it fails unless it does; the `agent-review` check runs this.

`sync` brings the latest `agent-review` run of the `pull_request` event on the head
commit in line with the verdict: it waits while the run is not completed and re-runs
it if its result differs. Prints `green`, `red <run url>` or `missing`; exits 1
unless the run ends green.

Usage:
  agent-review.py <pr> <head_sha>
  agent-review.py sync <pr> <head_sha>
"""

import json
import subprocess
import sys
import time

APPROVE = "Verdict: approve"
WORKFLOW = "agent-review.yml"
ATTEMPTS = 10
INTERVAL_SECONDS = 3


def gh_json(*args):
    return json.loads(
        subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout
    )


def reviews(pr):
    pages = gh_json(
        "api",
        "--paginate",
        "--slurp",
        f"repos/{{owner}}/{{repo}}/pulls/{pr}/reviews?per_page=100",
    )
    return [review for page in pages for review in page]


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


def latest_run(head_sha):
    runs = gh_json(
        "run",
        "list",
        "--workflow",
        WORKFLOW,
        "--event",
        "pull_request",
        "--commit",
        head_sha,
        "--limit",
        "1",
        "--json",
        "databaseId,attempt,url",
    )
    return runs[0] if runs else None


def wait(run):
    """Wait until the run is completed and tell whether it succeeded."""
    watched = subprocess.run(
        ["gh", "run", "watch", str(run["databaseId"]), "--exit-status"],
        stdout=subprocess.DEVNULL,
        check=False,
    )
    return watched.returncode == 0


def rerun(run):
    """Start a new attempt, or join one that is already running, e.g. from the
    other sync. Tell whether a new attempt started."""
    started = subprocess.run(
        ["gh", "run", "rerun", str(run["databaseId"])],
        capture_output=True,
        text=True,
        check=False,
    )
    # Until the new attempt shows up, `gh run watch` reports the old result.
    for attempt in range(ATTEMPTS):
        if attempt:
            time.sleep(INTERVAL_SECONDS)
        current = gh_json("run", "view", str(run["databaseId"]), "--json", "attempt")
        if current["attempt"] > run["attempt"]:
            return True
    sys.stderr.write(started.stderr)
    return False


def sync(pr, head_sha):
    run = latest_run(head_sha)
    if run is None:
        return "missing"
    green = wait(run)
    if green != approved(reviews(pr), head_sha):
        green = rerun(run) and wait(run)
    return "green" if green else f"red {run['url']}"


def main(argv):
    match argv:
        case ["sync", pr, head_sha]:
            result = sync(pr, head_sha)
            print(result)
            if result != "green":
                sys.exit(1)
        case [pr, head_sha] if pr != "sync":
            if not approved(reviews(pr), head_sha):
                sys.exit(f"No '{APPROVE}' review for {head_sha}")
        case _:
            sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
