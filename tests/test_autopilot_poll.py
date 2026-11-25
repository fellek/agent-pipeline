import json
import subprocess

import pytest
from conftest import load_script

SINCE = "2026-11-13T10:00:00Z"


@pytest.fixture
def poll(monkeypatch):
    module = load_script("autopilot-poll.py")
    monkeypatch.setattr(module, "dependencies", lambda number, relation: [])
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

    poll.wait([("answer", 48, SINCE)], sleep=no_sleep)

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

    poll.wait([("answer", 55, SINCE)], sleep=no_sleep)

    assert [e["number"] for e in events(capsys)] == [55]


def issue(number, *labels, association="OWNER"):
    return {
        "number": number,
        "title": "Neu",
        "labels": [{"name": n} for n in labels],
        "author_association": association,
    }


def test_labeled_issue_only_reported_in_new_issue_mode(monkeypatch, capsys, poll):
    calls = fake_gh(
        monkeypatch, poll, [issue(60), {**issue(61), "pull_request": {}}], [], []
    )

    poll.wait([("new_issue", "batch-1")], sleep=no_sleep)
    answer_events = poll.poll([("answer", 48, SINCE)])

    assert events(capsys) == [
        {"type": "labeled_issue", "number": 60, "title": "Neu", "labels": []}
    ]
    assert "labels=batch-1" in calls[0]
    assert answer_events == []
    assert "labels=" not in calls[2]


@pytest.mark.parametrize("label", ["question", "parked"])
def test_issue_with_skipped_label_is_ignored(monkeypatch, capsys, poll, label):
    fake_gh(
        monkeypatch,
        poll,
        [issue(60, "batch-1", label)],
        [],
        [issue(61, "batch-1")],
        [],
    )

    poll.wait([("new_issue", "batch-1")], sleep=no_sleep)

    assert [e["number"] for e in events(capsys)] == [61]


def fake_dependencies(monkeypatch, poll, **states):
    def dependencies(number, relation):
        return [{"state": s} for s in states.get(f"{relation}_{number}", [])]

    monkeypatch.setattr(poll, "dependencies", dependencies)


def test_issue_with_open_blocker_is_not_reported(monkeypatch, capsys, poll):
    fake_gh(monkeypatch, poll, [issue(60), issue(61)], [])
    fake_dependencies(monkeypatch, poll, blocked_by_60=["closed", "open"])

    poll.check([("new_issue", "ready")])

    assert [e["number"] for e in events(capsys)] == [61]


@pytest.mark.parametrize(
    ("blocker", "chosen", "labels"),
    [("open", 61, ["ready"]), ("closed", 60, ["ready", "enhancement"])],
    ids=["open", "closed"],
)
def test_next_skips_issue_with_open_blocker(
    monkeypatch, capsys, poll, blocker, chosen, labels
):
    calls = fake_gh(
        monkeypatch, poll, [issue(61, "ready"), issue(60, "ready", "enhancement")]
    )
    fake_dependencies(monkeypatch, poll, blocked_by_60=[blocker])

    poll.main(["next", "ready"])

    assert events(capsys) == [{"number": chosen, "title": "Neu", "labels": labels}]
    assert "labels=ready" in calls[0]


@pytest.mark.parametrize(
    ("blocked", "chosen"), [("open", 61), ("closed", 60)], ids=["open", "closed"]
)
def test_next_prefers_issue_blocking_an_open_issue(
    monkeypatch, capsys, poll, blocked, chosen
):
    fake_gh(monkeypatch, poll, [issue(60), issue(61), issue(62)])
    fake_dependencies(monkeypatch, poll, blocking_61=[blocked], blocking_62=[blocked])

    poll.main(["next", "ready"])

    assert [e["number"] for e in events(capsys)] == [chosen]


def test_next_without_candidates_prints_nothing(monkeypatch, capsys, poll):
    fake_gh(monkeypatch, poll, [issue(60, "parked")])

    poll.main(["next", "ready"])

    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "status", ["ready", "in-progress", "in-review", "approved", "question", "parked"]
)
def test_untriaged_skips_status_label(monkeypatch, capsys, poll, status):
    fake_gh(monkeypatch, poll, [issue(60, status), issue(61)])

    poll.main(["untriaged", "batch-1"])

    assert [e["number"] for e in events(capsys)] == [61]


def test_untriaged_reports_issue_without_status_label(monkeypatch, capsys, poll):
    calls = fake_gh(
        monkeypatch,
        poll,
        [
            issue(60, "followup"),
            issue(61, "batch-1"),
            issue(62, "bug", "enhancement"),
            {**issue(63), "pull_request": {}},
        ],
    )

    poll.main(["untriaged", "batch-1"])

    assert events(capsys) == [
        {"number": 60, "title": "Neu", "labels": ["followup"]},
        {"number": 62, "title": "Neu", "labels": ["bug", "enhancement"]},
    ]
    assert "labels=" not in calls[0]


def test_new_issue_wakes_on_untriaged_issue(monkeypatch, capsys, poll):
    fake_gh(monkeypatch, poll, [], [], [], [issue(60)])
    sleeps = []

    poll.wait([("new_issue", "ready")], sleep=sleeps.append)

    assert sleeps == [poll.INTERVAL_SECONDS]
    assert events(capsys) == [
        {"type": "untriaged_issue", "number": 60, "title": "Neu", "labels": []}
    ]


def test_next_selects_issue_with_selection_label_only(monkeypatch, capsys, poll):
    fake_gh(monkeypatch, poll, [issue(60, "batch-1")], [issue(60, "batch-1")])

    poll.main(["next", "batch-1"])
    poll.main(["untriaged", "batch-1"])

    assert [e["number"] for e in events(capsys)] == [60]


def test_dependencies_read_relation_endpoint(monkeypatch):
    poll = load_script("autopilot-poll.py")
    calls = fake_gh(monkeypatch, poll, [])

    poll.dependencies(60, "blocked_by")

    assert calls == ["repos/{owner}/{repo}/issues/60/dependencies/blocked_by"]


def test_keeps_polling_without_events(monkeypatch, capsys, poll):
    calls = fake_gh(monkeypatch, poll, [], [], [comment()])
    sleeps = []

    poll.wait([("answer", 48, SINCE)], sleep=sleeps.append)

    assert sleeps == [poll.INTERVAL_SECONDS] * 2
    assert len(calls) == 3
    assert len(events(capsys)) == 1


def test_new_commit_on_branch_is_printed(monkeypatch, capsys, poll):
    heads = ["abc", "abc", "def"]
    monkeypatch.setattr(poll, "branch_head", lambda branch: heads.pop(0))

    poll.wait([("patch", "issue-71-x", "abc")], sleep=no_sleep)

    assert events(capsys) == [{"type": "commit", "branch": "issue-71-x", "sha": "def"}]


def test_branch_head_reads_commit_sha(monkeypatch, poll):
    calls = []
    monkeypatch.setattr(poll, "gh_api", lambda *args: calls.append(args) or "def\n")

    assert poll.branch_head("issue-71-x") == "def"
    assert calls[0][0] == "repos/{owner}/{repo}/branches/issue-71-x"


GH_ERROR = subprocess.CalledProcessError(1, ["gh", "api"])


def test_keeps_polling_after_transient_gh_errors(monkeypatch, capsys, poll):
    fake_gh(monkeypatch, poll, GH_ERROR, [], GH_ERROR, GH_ERROR, [comment()])

    poll.wait([("answer", 48, SINCE)], sleep=no_sleep)

    assert len(events(capsys)) == 1


def test_fails_after_consecutive_gh_errors(monkeypatch, poll):
    fake_gh(monkeypatch, poll, *[GH_ERROR] * poll.MAX_FAILED_POLLS)

    with pytest.raises(subprocess.CalledProcessError):
        poll.wait([("answer", 48, SINCE)], sleep=no_sleep)


def test_github_now_reads_date_header(monkeypatch, poll):
    response = "HTTP/2.0 200 OK\nDate: Fri, 13 Nov 2026 10:00:00 GMT\n\n{}"
    monkeypatch.setattr(poll, "gh_api", lambda *args: response)

    assert poll.github_now() == SINCE


def test_github_now_fails_without_date_header(monkeypatch, poll):
    monkeypatch.setattr(poll, "gh_api", lambda *args: "HTTP/2.0 200 OK\n\n{}")

    with pytest.raises(RuntimeError):
        poll.github_now()


LATER = "2026-11-13T11:00:00Z"


def test_answers_use_cursor_per_issue_in_one_fetch(monkeypatch, capsys, poll):
    comments = [
        comment(number=48, created_at="2026-11-13T10:30:00Z"),
        comment(number=55, created_at="2026-11-13T10:30:00Z"),
        comment(number=55, created_at="2026-11-13T11:00:01Z", association="NONE"),
        comment(number=55, created_at="2026-11-13T11:00:02Z"),
    ]
    calls = fake_gh(monkeypatch, poll, comments)

    poll.wait([("answer", 48, SINCE), ("answer", 55, LATER)], sleep=no_sleep)

    assert [(e["number"], e["created_at"]) for e in events(capsys)] == [
        (48, "2026-11-13T10:30:00Z"),
        (55, "2026-11-13T11:00:02Z"),
    ]
    assert len(calls) == 1
    assert f"since={SINCE}" in calls[0]


def test_wait_ends_on_first_event_of_any_target(monkeypatch, capsys, poll):
    fake_gh(monkeypatch, poll, [], [], [], [], [issue(60)], [])
    heads = ["abc", "def"]
    monkeypatch.setattr(poll, "branch_head", lambda branch: heads.pop(0))
    targets = [
        ("answer", 48, SINCE),
        ("patch", "issue-71-x", "abc"),
        ("new_issue", "ready"),
    ]
    sleeps = []

    poll.wait(targets, sleep=sleeps.append)

    assert sleeps == [poll.INTERVAL_SECONDS]
    assert [e["type"] for e in events(capsys)] == ["commit", "labeled_issue"]


@pytest.mark.parametrize("comments", [[], [comment()]], ids=["none", "answer"])
def test_check_polls_once(monkeypatch, capsys, poll, comments):
    calls = fake_gh(monkeypatch, poll, comments)

    poll.check([("answer", 48, SINCE)])

    assert len(events(capsys)) == len(comments)
    assert len(calls) == 1


@pytest.mark.parametrize("command", ["wait", "check"])
def test_main_parses_target_list(monkeypatch, poll, command):
    calls = []
    monkeypatch.setattr(poll, command, lambda targets: calls.append(targets))

    poll.main(
        [command, "answer", "48", SINCE, "patch", "issue-71-x", "abc"]
        + ["new_issue", "batch-1"]
    )

    assert calls == [
        [
            ("answer", 48, SINCE),
            ("patch", "issue-71-x", "abc"),
            ("new_issue", "batch-1"),
        ]
    ]


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["wait"],
        ["check"],
        ["wait", "new_issue"],
        ["wait", "answer", "48"],
        ["wait", "answer", "x", SINCE],
        ["wait", "merge", "56", SINCE],
        ["wait", "patch", "issue-71-x"],
        ["check", "new_issue", "batch-1", SINCE],
        ["poll", "new_issue", "batch-1"],
        ["next"],
        ["next", "ready", "batch-1"],
        ["untriaged"],
        ["untriaged", "ready", "batch-1"],
    ],
)
def test_main_rejects_invalid_arguments(poll, argv):
    with pytest.raises(SystemExit):
        poll.main(argv)


@pytest.mark.parametrize(
    "association", ["CONTRIBUTOR", "NONE", "FIRST_TIME_CONTRIBUTOR"]
)
def test_untriaged_skips_issues_of_strangers(monkeypatch, poll, association):
    fake_gh(monkeypatch, poll, [issue(60, association=association), issue(61)])

    assert [i["number"] for i in poll.untriaged("ready")] == [61]


@pytest.mark.parametrize("association", ["OWNER", "MEMBER", "COLLABORATOR"])
def test_untriaged_takes_issues_of_the_team(monkeypatch, poll, association):
    fake_gh(monkeypatch, poll, [issue(60, association=association)])

    assert [i["number"] for i in poll.untriaged("ready")] == [60]


def labeled(login, name="ready"):
    return {"event": "labeled", "label": {"name": name}, "actor": {"login": login}}


def fake_permissions(monkeypatch, poll, **permissions):
    asked = []

    def gh_api(path):
        login = path.split("/")[-2]
        asked.append(login)
        return json.dumps({"permission": permissions[login]})

    monkeypatch.setattr(poll, "gh_api", gh_api)
    return asked


@pytest.mark.parametrize(
    ("label_events", "expected"),
    [
        ([], []),
        ([labeled("maintainer")], [60]),
        ([labeled("guest")], []),
        ([labeled("maintainer"), labeled("guest")], []),
        ([labeled("guest"), labeled("maintainer")], [60]),
        ([labeled("maintainer", name="bug")], []),
        ([{"event": "commented", "actor": {"login": "maintainer"}}], []),
    ],
    ids=[
        "never_labeled",
        "labeled_by_writer",
        "labeled_by_reader",
        "relabeled_by_reader",
        "relabeled_by_writer",
        "other_label",
        "other_event",
    ],
)
def test_stranger_issue_is_a_candidate_only_if_a_writer_labeled_it(
    monkeypatch, poll, label_events, expected
):
    calls = fake_gh(
        monkeypatch, poll, [issue(60, "ready", association="NONE")], label_events
    )
    fake_permissions(monkeypatch, poll, maintainer="admin", guest="read")

    assert [i["number"] for i in poll.candidates("ready")] == expected
    assert calls[1] == "repos/{owner}/{repo}/issues/60/events?per_page=100"


def test_team_issue_needs_no_label_check(monkeypatch, poll):
    calls = fake_gh(monkeypatch, poll, [issue(60, "ready", association="MEMBER")])

    assert [i["number"] for i in poll.candidates("ready")] == [60]
    assert len(calls) == 1
