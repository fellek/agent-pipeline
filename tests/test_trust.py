import pytest
import trust

LABELED = {
    "event": "labeled",
    "label": {"name": "ready"},
    "actor": {"login": "maintainer"},
    "created_at": "2026-01-02T00:00:00Z",
}


def permission(login):
    return {"maintainer": "write", "guest": "read"}.get(login)


def event(kind, at, **fields):
    return {"event": kind, "created_at": at, **fields}


@pytest.mark.parametrize(
    ("events", "edited", "label", "expected"),
    [
        ([LABELED], "", "ready", True),
        ([LABELED], "", None, True),
        ([], "", None, False),
        ([LABELED], "2026-01-03T00:00:00Z", None, False),
        ([LABELED], "2026-01-01T00:00:00Z", None, True),
        ([LABELED, event("renamed", "2026-01-03T00:00:00Z")], "", None, False),
        ([event("renamed", "2026-01-01T00:00:00Z"), LABELED], "", None, True),
        ([{**LABELED, "actor": {"login": "guest"}}], "", None, False),
        ([{**LABELED, "actor": {"login": "bot"}}], "", None, False),
        ([{**LABELED, "label": {"name": "in-progress"}}], "", None, False),
        ([LABELED], "", "bug", False),
    ],
    ids=[
        "selection_label_of_writer",
        "any_label_of_writer",
        "never_labeled",
        "edited_after_label",
        "edited_before_label",
        "renamed_after_label",
        "renamed_before_label",
        "label_of_reader",
        "label_of_bot",
        "status_label_does_not_count",
        "other_than_selection_label",
    ],
)
def test_approved(events, edited, label, expected):
    assert trust.approved(events, edited, permission, label) is expected
