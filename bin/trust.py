"""Which GitHub content of an issue may reach a fork or the gate review.

Text of the repository's owner, members and collaborators does. A stranger's issue
does only while its title and body are what a writer saw when labeling it: the
latest label by a writer, with no edit or rename after it.
"""

TRUSTED = {"OWNER", "MEMBER", "COLLABORATOR"}
WRITERS = {"admin", "maintain", "write"}
STATUS_LABELS = {"ready", "in-progress", "in-review", "approved", "question", "parked"}
# Set by the autopilot while it works on an issue; `ready` it sets only on the
# issues of the team, so on a stranger's issue it comes from a person.
WORK_LABELS = STATUS_LABELS - {"ready"}
EDITED_QUERY = (
    "query($owner: String!, $repo: String!, $n: Int!)"
    " { repository(owner: $owner, name: $repo) { issue(number: $n) { lastEditedAt } } }"
)


def trusted_comments(comments, key):
    return [c for c in comments if c[key] in TRUSTED]


def approved(events, edited, permission, label=None):
    """Whether a writer labeled the issue after its last edit and rename.

    `label` is the selection label; without it any label but WORK_LABELS counts.
    `permission(login)` is the login's permission on the repository, or None.
    """
    labeled = [
        e
        for e in events
        if e["event"] == "labeled"
        and e.get("actor")
        and (
            e["label"]["name"] == label
            if label
            else e["label"]["name"] not in WORK_LABELS
        )
    ]
    if not labeled:
        return False
    at = labeled[-1]["created_at"]
    if edited and edited > at:
        return False
    if any(e["event"] == "renamed" and e["created_at"] > at for e in events):
        return False
    return permission(labeled[-1]["actor"]["login"]) in WRITERS
