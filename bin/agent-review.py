#!/usr/bin/env python3
"""Check that the latest review on the head commit is an approve of the gate.

With the Actions secret PIPELINE_REVIEW_KEY in the environment only reviews with a
valid attestation of the gate count (see attestation.py). Without it, the latest
review whose first line is `Verdict: approve` counts, with a warning, until the
secret is set.

Without `sync` or `audit` it fails unless the review is an approve; the
`agent-review` check runs this.

`sync` brings the latest `agent-review` run of the `pull_request` event on the head
commit in line with the verdict: it waits while the run is not completed and re-runs
it if its result differs. Prints `green`, `red <run url>`, `missing` or, after an
overall deadline of 45 minutes, `timeout`; exits 1
unless the run ends in line with the verdict, so a red run after a review without
an approve is no failure.

`await` is `sync` without the re-run, for the orchestrator, whose token may only
read Actions: on a mismatch it waits up to 10 minutes for the new attempt that
agent-review-sync.yml starts.

`audit` checks a commit pushed to the default branch: it must be the merge of a
pull request whose head has an attested approve and passed runs. Otherwise it
opens a followup issue and exits 1. Without the key it only warns.

Usage:
  agent-review.py <pr> <head_sha>
  agent-review.py sync <pr> <head_sha>
  agent-review.py await <pr> <head_sha>
  agent-review.py audit <sha>
"""

import json
import os
import subprocess
import sys
import time

import attestation

APPROVE = "Verdict: approve"
WORKFLOW = "agent-review.yml"
ATTEMPTS = 10
INTERVAL_SECONDS = 3
AWAIT_ATTEMPTS = 20
AWAIT_INTERVAL_SECONDS = 30
DEADLINE_SECONDS = 45 * 60


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


def review_key():
    return os.environ.get("PIPELINE_REVIEW_KEY") or None


def warn_without_key():
    print(
        "::warning::PIPELINE_REVIEW_KEY is not set, so a review counts without "
        "attestation of the gate",
        file=sys.stderr,
    )


def approved(reviews, pr, head_sha, key):
    if key:
        verdict = attestation.latest_verdict(reviews, key, pr, head_sha)
        return verdict == attestation.APPROVE
    warn_without_key()
    return text_approved(reviews, head_sha)


def text_approved(reviews, head_sha):
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


def wait(run, deadline):
    """Wait until the run is completed and tell whether it succeeded.

    Raises subprocess.TimeoutExpired once the deadline has passed."""
    watched = subprocess.run(
        ["gh", "run", "watch", str(run["databaseId"]), "--exit-status"],
        stdout=subprocess.DEVNULL,
        check=False,
        timeout=max(0, deadline - time.monotonic()),
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
    if new_attempt(run, ATTEMPTS, INTERVAL_SECONDS):
        return True
    sys.stderr.write(started.stderr)
    return False


def new_attempt(run, attempts, interval):
    # Until the new attempt shows up, `gh run watch` reports the old result.
    for attempt in range(attempts):
        if attempt:
            time.sleep(interval)
        current = gh_json("run", "view", str(run["databaseId"]), "--json", "attempt")
        if current["attempt"] > run["attempt"]:
            return True
    return False


def sync(pr, head_sha, may_rerun=True):
    deadline = time.monotonic() + DEADLINE_SECONDS
    run = latest_run(head_sha)
    if run is None:
        return "missing", False
    try:
        green = wait(run, deadline)
        approve = approved(reviews(pr), pr, head_sha, review_key())
        if green != approve:
            if may_rerun:
                started = rerun(run)
            else:
                started = new_attempt(run, AWAIT_ATTEMPTS, AWAIT_INTERVAL_SECONDS)
            green = started and wait(run, deadline)
    except subprocess.TimeoutExpired:
        return "timeout", False
    return ("green" if green else f"red {run['url']}"), green == approve


def merged_pull_request(sha):
    pulls = gh_json("api", f"repos/{{owner}}/{{repo}}/commits/{sha}/pulls")
    return next(
        (p for p in pulls if p["merged_at"] and p["merge_commit_sha"] == sha), None
    )


def audit_problems(sha, key):
    pull = merged_pull_request(sha)
    if pull is None:
        return ["no merged pull request has this commit as its merge"]
    pr, head = pull["number"], pull["head"]["sha"]
    problems = []
    if attestation.latest_verdict(reviews(pr), key, pr, head) != attestation.APPROVE:
        problems.append(f"#{pr} has no attested approve on its head {head}")
    runs = gh_json(
        "run",
        "list",
        "--commit",
        head,
        "--limit",
        "100",
        "--json",
        "name,status,conclusion",
    )
    if failed := attestation.failed_runs(runs):
        problems.append(f"#{pr} merged with runs not passed: {', '.join(failed)}")
    return problems


def audit(sha):
    key = review_key()
    if not key:
        warn_without_key()
        return
    problems = audit_problems(sha, key)
    if not problems:
        return
    body = "\n".join(f"- {problem}" for problem in problems)
    subprocess.run(
        [
            "gh",
            "issue",
            "create",
            "--label",
            "followup",
            "--title",
            f"Merge ohne gültige Review-Attestierung: {sha[:12]}",
            "--body",
            f"Commit {sha} auf dem Default-Branch:\n\n{body}",
        ],
        check=True,
    )
    sys.exit("\n".join(problems))


def main(argv):
    match argv:
        case ["sync" | "await" as command, pr, head_sha]:
            result, in_line = sync(pr, head_sha, may_rerun=command == "sync")
            print(result)
            if not in_line:
                sys.exit(1)
        case ["audit", sha]:
            audit(sha)
        case [pr, head_sha] if pr not in ("sync", "await", "audit"):
            if not approved(reviews(pr), pr, head_sha, review_key()):
                sys.exit(f"No approve of the gate for {head_sha}")
        case _:
            sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
