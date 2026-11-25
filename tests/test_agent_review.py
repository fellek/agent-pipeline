import json
import subprocess

import attestation
import pytest
from conftest import load_script

HEAD = "head"


@pytest.fixture
def gate():
    return load_script("agent-review.py")


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
        ([review(commit_id="old"), review(body="")], False),
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
        "thread_reply_after_push",
    ],
)
def test_approved_by_text_without_key(gate, reviews, expected, capsys):
    assert gate.approved(reviews, 49, HEAD, None) is expected
    assert "PIPELINE_REVIEW_KEY is not set" in capsys.readouterr().err


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


RUN = {"databaseId": 7, "attempt": 1, "url": "https://example.test/runs/7"}


@pytest.fixture
def sync_gate(monkeypatch, gate):
    monkeypatch.setattr(gate.time, "sleep", lambda seconds: None)
    return gate


def fake_sync_gh(monkeypatch, reviews, runs, watch_exits, attempts=(), rerun_exit=0):
    """Fakes gh for `sync`: `attempts` are the attempts `gh run view` reports."""
    calls = []
    watch_exits = iter(watch_exits)
    attempts = iter(attempts)

    def run(args, **kwargs):
        calls.append(args)
        match args[1:3]:
            case ["api", _]:
                stdout = json.dumps([reviews])
            case ["run", "list"]:
                stdout = json.dumps(runs)
            case ["run", "view"]:
                stdout = json.dumps({"attempt": next(attempts)})
            case ["run", "watch"]:
                return subprocess.CompletedProcess(args, next(watch_exits))
            case ["run", "rerun"]:
                return subprocess.CompletedProcess(
                    args, rerun_exit, stdout="", stderr="already running\n"
                )
        return subprocess.CompletedProcess(args, 0, stdout=stdout)

    monkeypatch.setattr(subprocess, "run", run)
    return calls


def commands(calls):
    return [args[1:3] for args in calls]


def run_sync(gate, capsys):
    try:
        gate.main(["sync", "49", HEAD])
        code = 0
    except SystemExit as exit_info:
        code = exit_info.code
    return code, capsys.readouterr().out


def test_sync_lists_push_runs_of_the_head_commit(monkeypatch, capsys, sync_gate):
    calls = fake_sync_gh(monkeypatch, [APPROVE], [RUN], watch_exits=[0])

    assert run_sync(sync_gate, capsys) == (0, "green\n")
    assert calls[0] == [
        "gh",
        "run",
        "list",
        "--workflow",
        "agent-review.yml",
        "--event",
        "pull_request",
        "--commit",
        HEAD,
        "--limit",
        "1",
        "--json",
        "databaseId,attempt,url",
    ]
    assert calls[1] == ["gh", "run", "watch", "7", "--exit-status"]
    assert ["run", "rerun"] not in commands(calls)


def test_sync_reruns_red_run_after_approve(monkeypatch, capsys, sync_gate):
    calls = fake_sync_gh(
        monkeypatch, [CHANGES, APPROVE], [RUN], watch_exits=[1, 0], attempts=[1, 2]
    )

    assert run_sync(sync_gate, capsys) == (0, "green\n")
    assert calls[3] == ["gh", "run", "rerun", "7"]
    assert commands(calls)[4:] == [["run", "view"], ["run", "view"], ["run", "watch"]]


def test_sync_reruns_green_run_after_changes_requested(monkeypatch, capsys, sync_gate):
    calls = fake_sync_gh(
        monkeypatch, [APPROVE, CHANGES], [RUN], watch_exits=[0, 1], attempts=[2]
    )

    assert run_sync(sync_gate, capsys) == (0, f"red {RUN['url']}\n")
    assert ["run", "rerun"] in commands(calls)


def test_sync_fails_when_rerun_stays_green_after_changes_requested(
    monkeypatch, capsys, sync_gate
):
    fake_sync_gh(
        monkeypatch, [APPROVE, CHANGES], [RUN], watch_exits=[0, 0], attempts=[2]
    )

    assert run_sync(sync_gate, capsys) == (1, "green\n")


def test_sync_keeps_red_run_without_approve(monkeypatch, capsys, sync_gate):
    calls = fake_sync_gh(monkeypatch, [CHANGES], [RUN], watch_exits=[1])

    assert run_sync(sync_gate, capsys) == (0, f"red {RUN['url']}\n")
    assert ["run", "rerun"] not in commands(calls)


def test_sync_ignores_thread_reply_after_approve(monkeypatch, capsys, sync_gate):
    calls = fake_sync_gh(monkeypatch, [APPROVE, review(body="")], [RUN], [0])

    assert run_sync(sync_gate, capsys) == (0, "green\n")
    assert ["run", "rerun"] not in commands(calls)


def test_sync_joins_rerun_that_is_already_running(monkeypatch, capsys, sync_gate):
    calls = fake_sync_gh(
        monkeypatch,
        [APPROVE],
        [RUN],
        watch_exits=[1, 0],
        attempts=[2],
        rerun_exit=1,
    )

    assert run_sync(sync_gate, capsys) == (0, "green\n")
    assert commands(calls)[-1] == ["run", "watch"]


def test_sync_fails_when_no_rerun_starts(monkeypatch, capsys, sync_gate):
    calls = fake_sync_gh(
        monkeypatch,
        [APPROVE],
        [RUN],
        watch_exits=[1],
        attempts=[1] * sync_gate.ATTEMPTS,
        rerun_exit=1,
    )

    with pytest.raises(SystemExit):
        sync_gate.main(["sync", "49", HEAD])

    output = capsys.readouterr()
    assert output.out == f"red {RUN['url']}\n"
    assert "already running" in output.err
    assert commands(calls).count(["run", "watch"]) == 1


def test_sync_reports_missing_run(monkeypatch, capsys, sync_gate):
    calls = fake_sync_gh(monkeypatch, [APPROVE], [], watch_exits=[])

    assert run_sync(sync_gate, capsys) == (1, "missing\n")
    assert len(calls) == 1


@pytest.mark.parametrize(
    "argv", [[], ["49"], ["49", HEAD, "extra"], ["sync", HEAD], ["sync", "49"]]
)
def test_main_rejects_invalid_arguments(gate, argv):
    with pytest.raises(SystemExit):
        gate.main(argv)


SHA = "a" * 40
KEY = "k" * 64


def attested(verdict=attestation.APPROVE, key=KEY, sha=SHA, pr=49, state="COMMENTED"):
    line = attestation.line(key, pr, sha, verdict, "s1")
    return {"body": f"Verdict: approve\n\n{line}", "commit_id": sha, "state": state}


@pytest.mark.parametrize(
    ("reviews", "expected"),
    [
        ([attested()], True),
        ([attested(attestation.CHANGES_REQUESTED)], False),
        ([attested(), attested(attestation.CHANGES_REQUESTED)], False),
        ([attested(attestation.CHANGES_REQUESTED), attested()], True),
        ([attested(), review(body="Verdict: changes requested", commit_id=SHA)], True),
        ([review(commit_id=SHA)], False),
        ([attested(key="other")], False),
        ([attested(pr=50)], False),
        ([attested(sha="b" * 40)], False),
        ([attested(state="DISMISSED")], False),
    ],
    ids=[
        "attested_approve",
        "attested_changes",
        "approve_then_changes",
        "changes_then_approve",
        "unattested_review_after_approve_is_ignored",
        "same_account_verdict_without_attestation",
        "wrong_key",
        "other_pull_request",
        "other_commit",
        "dismissed",
    ],
)
def test_approved_with_key_counts_only_attested_reviews(gate, reviews, expected):
    assert gate.approved(reviews, 49, SHA, KEY) is expected


def test_forged_mac_is_ignored(gate):
    body = attested()["body"]
    forged = body[:-10] + ("0" * 6) + body[-4:]
    assert gate.approved([review(body=forged, commit_id=SHA)], 49, SHA, KEY) is False


def test_main_reads_key_from_environment(monkeypatch, gate):
    monkeypatch.setenv("PIPELINE_REVIEW_KEY", KEY)
    fake_gh(monkeypatch, [[review(commit_id=SHA)]])
    with pytest.raises(SystemExit):
        gate.main(["49", SHA])
    fake_gh(monkeypatch, [[attested()]])
    gate.main(["49", SHA])


def fake_audit_gh(monkeypatch, pulls, reviews, runs):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if args[1:3] == ["issue", "create"]:
            return subprocess.CompletedProcess(args, 0, stdout="")
        if args[1] == "run":
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps(runs))
        if args[-1].endswith("/pulls"):
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps(pulls))
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps([reviews]))

    monkeypatch.setattr(subprocess, "run", run)
    return calls


MERGE = "m" * 40
MERGED = {
    "number": 49,
    "merged_at": "t",
    "merge_commit_sha": MERGE,
    "head": {"sha": SHA},
}
GREEN = [{"name": "CI", "status": "completed", "conclusion": "success"}]


def test_audit_passes_merge_of_attested_pull_request(monkeypatch, gate):
    monkeypatch.setenv("PIPELINE_REVIEW_KEY", KEY)
    calls = fake_audit_gh(monkeypatch, [MERGED], [attested()], GREEN)
    gate.main(["audit", MERGE])
    assert not any(args[1:3] == ["issue", "create"] for args in calls)


@pytest.mark.parametrize(
    ("pulls", "reviews", "runs", "problem"),
    [
        ([], [], GREEN, "no merged pull request"),
        ([{**MERGED, "merge_commit_sha": "x"}], [], GREEN, "no merged pull request"),
        ([MERGED], [review(commit_id=SHA)], GREEN, "#49 has no attested approve"),
        (
            [MERGED],
            [attested()],
            [{"name": "CI", "status": "completed", "conclusion": "failure"}],
            "runs not passed: CI",
        ),
    ],
)
def test_audit_opens_issue_for_merge_without_gates(
    monkeypatch, gate, pulls, reviews, runs, problem
):
    monkeypatch.setenv("PIPELINE_REVIEW_KEY", KEY)
    calls = fake_audit_gh(monkeypatch, pulls, reviews, runs)
    with pytest.raises(SystemExit) as error:
        gate.main(["audit", MERGE])
    assert problem in error.value.code
    created = next(args for args in calls if args[1:3] == ["issue", "create"])
    assert created[created.index("--label") + 1] == "followup"
    assert problem in created[created.index("--body") + 1]


def test_audit_without_key_only_warns(monkeypatch, gate, capsys):
    monkeypatch.delenv("PIPELINE_REVIEW_KEY", raising=False)
    calls = fake_audit_gh(monkeypatch, [], [], [])
    gate.main(["audit", MERGE])
    assert calls == []
    assert "PIPELINE_REVIEW_KEY is not set" in capsys.readouterr().err


def test_sync_prints_timeout_after_the_deadline(monkeypatch, capsys, sync_gate):
    def run(args, **kwargs):
        if args[1:3] == ["run", "list"]:
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps([RUN]))
        assert 0 < kwargs["timeout"] <= sync_gate.DEADLINE_SECONDS
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", run)

    assert run_sync(sync_gate, capsys) == (1, "timeout\n")
