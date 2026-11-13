import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / ".github" / "scripts" / "autopilot-poll.py"
SINCE = "2026-11-13T10:00:00Z"


@pytest.fixture
def poll():
    spec = importlib.util.spec_from_file_location("autopilot_poll", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def comment(number=48, created_at="2026-11-13T10:00:01Z", association="OWNER"):
    return {
        "issue_url": f"https://api.github.com/repos/o/r/issues/{number}",
        "html_url": f"https://github.com/o/r/issues/{number}#issuecomment-1",
        "created_at": created_at,
        "author_association": association,
        "body": "ja",
    }


def fake_gh(monkeypatch, poll, *responses):
    calls = []
    pending = list(responses)

    def gh(path):
        calls.append(path)
        response = pending.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(poll, "gh", gh)
    return calls


def events(capsys):
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def no_sleep(seconds):
    pass


def test_owner_comment_after_cursor_is_printed(monkeypatch, capsys, poll):
    fake_gh(monkeypatch, poll, [comment()])

    poll.wait("answer", 48, SINCE, sleep=no_sleep)

    assert events(capsys) == [
        {
            "type": "comment",
            "number": 48,
            "url": "https://github.com/o/r/issues/48#issuecomment-1",
            "created_at": "2026-11-13T10:00:01Z",
            "body": "ja",
        }
    ]


@pytest.mark.parametrize(
    "ignored",
    [
        comment(created_at="2026-11-13T09:59:59Z"),
        comment(created_at=SINCE),
        comment(association="CONTRIBUTOR"),
        comment(number=47),
    ],
    ids=["before_cursor", "on_cursor", "not_owner", "other_issue"],
)
def test_comment_is_ignored(monkeypatch, capsys, poll, ignored):
    fake_gh(monkeypatch, poll, [ignored], [comment(number=55)])

    poll.wait("answer", 55, SINCE, sleep=no_sleep)

    assert [e["number"] for e in events(capsys)] == [55]


def test_merge_mode_reports_owner_reviews_and_review_comments(
    monkeypatch, capsys, poll
):
    review_comment = {**comment(), "html_url": "rc"}
    review = {**comment(), "html_url": "rv", "submitted_at": "2026-11-13T10:00:02Z"}
    pending_review = {**review, "submitted_at": None}
    old_review = {**review, "submitted_at": SINCE}
    calls = fake_gh(
        monkeypatch,
        poll,
        [],
        [review_comment, comment(association="CONTRIBUTOR")],
        [review, pending_review, old_review],
    )

    poll.wait("merge", 56, SINCE, sleep=no_sleep)

    assert [(e["url"], e["created_at"]) for e in events(capsys)] == [
        ("rc", "2026-11-13T10:00:01Z"),
        ("rv", "2026-11-13T10:00:02Z"),
    ]
    assert calls[1].startswith("repos/{owner}/{repo}/pulls/56/comments?")
    assert calls[2].startswith("repos/{owner}/{repo}/pulls/56/reviews?")


def test_ready_issue_only_reported_in_new_issue_mode(monkeypatch, capsys, poll):
    issue = {"number": 60, "title": "Neu"}
    calls = fake_gh(monkeypatch, poll, [issue, {**issue, "pull_request": {}}], [])

    poll.wait("new_issue", None, SINCE, sleep=no_sleep)
    answer_events = poll.poll("answer", 48, SINCE)

    assert events(capsys) == [{"type": "ready_issue", "number": 60, "title": "Neu"}]
    assert "labels=ready" in calls[0]
    assert answer_events == []
    assert "labels=ready" not in calls[1]


def test_keeps_polling_without_events(monkeypatch, capsys, poll):
    calls = fake_gh(monkeypatch, poll, [], [], [comment()])
    sleeps = []

    poll.wait("answer", 48, SINCE, sleep=sleeps.append)

    assert sleeps == [poll.INTERVAL_SECONDS] * 2
    assert len(calls) == 3
    assert len(events(capsys)) == 1


GH_ERROR = subprocess.CalledProcessError(1, ["gh", "api"])


def test_keeps_polling_after_transient_gh_errors(monkeypatch, capsys, poll):
    fake_gh(monkeypatch, poll, GH_ERROR, [], GH_ERROR, GH_ERROR, [comment()])

    poll.wait("answer", 48, SINCE, sleep=no_sleep)

    assert len(events(capsys)) == 1


def test_fails_after_consecutive_gh_errors(monkeypatch, poll):
    fake_gh(monkeypatch, poll, *[GH_ERROR] * poll.MAX_FAILED_POLLS)

    with pytest.raises(subprocess.CalledProcessError):
        poll.wait("answer", 48, SINCE, sleep=no_sleep)


def test_github_now_reads_date_header(monkeypatch, poll):
    response = "HTTP/2.0 200 OK\nDate: Fri, 13 Nov 2026 10:00:00 GMT\n\n{}"
    monkeypatch.setattr(poll, "gh_api", lambda *args: response)

    assert poll.github_now() == SINCE


def test_github_now_fails_without_date_header(monkeypatch, poll):
    monkeypatch.setattr(poll, "gh_api", lambda *args: "HTTP/2.0 200 OK\n\n{}")

    with pytest.raises(RuntimeError):
        poll.github_now()


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["wait", "answer", "48", SINCE], ("answer", 48, SINCE)),
        (["wait", "merge", "56", SINCE], ("merge", 56, SINCE)),
        (["wait", "new_issue"], ("new_issue", None, None)),
    ],
)
def test_main_dispatches_wait(monkeypatch, poll, argv, expected):
    calls = []
    monkeypatch.setattr(poll, "wait", lambda *args: calls.append(args))

    poll.main(argv)

    assert calls == [expected]


@pytest.mark.parametrize(
    "argv", [[], ["wait", "new_issue", SINCE], ["wait", "answer", "48"]]
)
def test_main_rejects_invalid_arguments(poll, argv):
    with pytest.raises(SystemExit):
        poll.main(argv)
