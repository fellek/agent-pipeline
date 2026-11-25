"""Review attestations of the gate and the checks that read them.

The gate ends the body of each review it posts with a line

  <!-- pipeline-attestation v1 pr=<pr> sha=<sha> verdict=<verdict> session=<id> mac=<hmac> -->

where the HMAC-SHA256 over the fields is keyed with the review key of the
project. Only the gate holds the key on the host and the Actions secret
PIPELINE_REVIEW_KEY in the repository, so a review typed by anyone else has no
valid attestation, whatever its author or text.
"""

import hashlib
import hmac
import re

APPROVE = "approve"
CHANGES_REQUESTED = "changes-requested"
LINE = re.compile(
    r"<!-- pipeline-attestation v1 pr=(\d+) sha=([0-9a-f]{40}) "
    r"verdict=(approve|changes-requested) session=([\w-]+) mac=([0-9a-f]{64}) -->"
)
# Their runs follow the attestation, so they cannot gate it.
REVIEW_WORKFLOWS = {"agent-review", "agent-review-sync"}
PASSED = {"success", "skipped", "neutral"}


def mac(key, pr, sha, verdict, session):
    message = f"v1 pr={pr} sha={sha} verdict={verdict} session={session}"
    return hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest()


def line(key, pr, sha, verdict, session):
    return (
        f"<!-- pipeline-attestation v1 pr={pr} sha={sha} verdict={verdict} "
        f"session={session} mac={mac(key, pr, sha, verdict, session)} -->"
    )


def verdict(body, key, pr, sha):
    """The verdict of a valid attestation in the body for pr and sha, else None."""
    for match in LINE.finditer(body or ""):
        found_pr, found_sha, found, session, found_mac = match.groups()
        if (
            int(found_pr) == int(pr)
            and found_sha == sha
            and hmac.compare_digest(found_mac, mac(key, pr, sha, found, session))
        ):
            return found
    return None


def latest_verdict(reviews, key, pr, sha):
    """The verdict of the latest attested review on sha, or None."""
    verdicts = [
        found
        for review in reviews
        if review["commit_id"] == sha
        and review["state"] != "DISMISSED"
        and (found := verdict(review["body"], key, pr, sha))
    ]
    return verdicts[-1] if verdicts else None


def failed_runs(runs):
    """Names of the workflows whose latest run on a commit did not pass.

    runs are the entries of `gh run list --json name,status,conclusion,attempt`,
    newest first. Without any run the commit counts as not passed.
    """
    latest = {}
    for run in runs:
        if run["name"] not in REVIEW_WORKFLOWS:
            latest.setdefault(run["name"], run)
    if not latest:
        return ["no CI run"]
    return sorted(
        name
        for name, run in latest.items()
        if run["status"] != "completed" or run["conclusion"] not in PASSED
    )
