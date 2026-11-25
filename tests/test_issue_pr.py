import json
import subprocess

import pytest
from conftest import load_script


@pytest.fixture
def script():
    return load_script("issue-pr.py")


def pr(number, branch, closes, *reviews):
    return {
        "number": number,
        "headRefName": branch,
        "closingIssuesReferences": [{"number": n} for n in closes],
        "reviews": [
            review if isinstance(review, dict) else gate_review(number, review)
            for review in reviews
        ],
    }


def gate_review(pr, verdict, association="OWNER"):
    line = (
        f"<!-- pipeline-attestation v1 pr={pr} sha={'a' * 40} verdict={verdict} "
        f"session=s1 mac={'b' * 64} -->"
    )
    return {"body": f"Verdict: x\n\n{line}", "authorAssociation": association}


def fake_gh(monkeypatch, prs, state="OPEN"):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        out = {"issue": {"state": state}, "pr": prs}[args[1]]
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(out))

    monkeypatch.setattr(subprocess, "run", run)
    return calls


def test_finds_pr_on_branch_without_issue_number(monkeypatch, script):
    fake_gh(monkeypatch, [pr(169, "claude/lucid-lamport-qamrtq", [168])])

    assert script.find("168") == {
        "state": "OPEN",
        "pr": 169,
        "branch": "claude/lucid-lamport-qamrtq",
        "review_rounds": 0,
    }


def test_ignores_pr_closing_another_issue(monkeypatch, script):
    fake_gh(monkeypatch, [pr(7, "issue-5-x", [5])])

    assert script.find("6") == {
        "state": "OPEN",
        "pr": None,
        "branch": None,
        "review_rounds": 0,
    }


def test_no_pr_gives_nulls(monkeypatch, script):
    fake_gh(monkeypatch, [])

    result = script.find("6")

    assert result["pr"] is None
    assert result["branch"] is None


def test_counts_only_changes_requested_reviews_of_the_gate(monkeypatch, script):
    reviews = [
        "changes-requested",
        "approve",
        "changes-requested",
        {"body": "Verdict: changes requested", "authorAssociation": "OWNER"},
        gate_review(7, "changes-requested", association="NONE"),
        gate_review(8, "changes-requested"),
    ]
    fake_gh(monkeypatch, [pr(7, "b", [6], *reviews)])

    assert script.find("6")["review_rounds"] == 2


def test_passes_issue_state_through(monkeypatch, script):
    fake_gh(monkeypatch, [], state="CLOSED")

    assert script.find("6")["state"] == "CLOSED"


def test_main_prints_json(monkeypatch, capsys, script):
    fake_gh(monkeypatch, [pr(7, "b", [6])])

    script.main(["6"])

    assert json.loads(capsys.readouterr().out)["pr"] == 7


@pytest.mark.parametrize("argv", [[], ["6", "extra"], ["x"]])
def test_main_rejects_invalid_arguments(script, argv):
    with pytest.raises(SystemExit) as exit_info:
        script.main(argv)

    assert "Usage" in str(exit_info.value.code)
