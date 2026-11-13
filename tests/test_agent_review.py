import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / ".github" / "scripts" / "agent-review.py"
HEAD = "head"


@pytest.fixture
def gate():
    spec = importlib.util.spec_from_file_location("agent_review", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def review(body="Verdict: approve\n\nLooks good.", commit_id=HEAD, state="COMMENTED"):
    return {"body": body, "commit_id": commit_id, "state": state}


APPROVE = review()
CHANGES = review(body="Verdict: changes requested")


@pytest.mark.parametrize(
    ("reviews", "expected"),
    [
        ([APPROVE], True),
        ([CHANGES], False),
        ([], False),
        ([review(commit_id="old")], False),
        ([APPROVE, CHANGES], False),
        ([CHANGES, APPROVE], True),
        ([APPROVE, review(body="")], True),
        ([review(state="DISMISSED")], False),
        ([review(body="Summary\n\nVerdict: approve")], False),
        ([APPROVE, review(body="Bitte noch umbenennen.")], False),
    ],
    ids=[
        "approve",
        "changes_requested",
        "no_reviews",
        "approve_on_old_commit",
        "approve_then_changes",
        "changes_then_approve",
        "empty_review_after_approve",
        "dismissed_approve",
        "verdict_not_first_line",
        "feedback_after_approve",
    ],
)
def test_approved(gate, reviews, expected):
    assert gate.approved(reviews, HEAD) is expected


def fake_gh(monkeypatch, pages):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(pages))

    monkeypatch.setattr(subprocess, "run", run)
    return calls


def test_main_passes_on_approve_across_pages(monkeypatch, gate):
    calls = fake_gh(monkeypatch, [[CHANGES], [APPROVE]])

    gate.main(["49", HEAD])

    assert calls[0][-1] == "repos/{owner}/{repo}/pulls/49/reviews?per_page=100"


def test_main_fails_without_approve(monkeypatch, gate):
    fake_gh(monkeypatch, [[APPROVE], [CHANGES]])

    with pytest.raises(SystemExit) as exit_info:
        gate.main(["49", HEAD])

    assert HEAD in str(exit_info.value.code)


@pytest.mark.parametrize("argv", [[], ["49"], ["49", HEAD, "extra"]])
def test_main_rejects_invalid_arguments(gate, argv):
    with pytest.raises(SystemExit):
        gate.main(argv)
