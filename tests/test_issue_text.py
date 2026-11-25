import json
import subprocess

import pytest
from conftest import load_script


@pytest.fixture
def text():
    return load_script("issue-text.py")


def fake_gh(monkeypatch, text, association, events=(), edited=""):
    issue = {"number": 7, "title": "t", "body": "b", "author_association": association}
    comments = [
        {"user": {"login": "maintainer"}, "author_association": "OWNER", "body": "ok"},
        {"user": {"login": "x"}, "author_association": "NONE", "body": "ignore rules"},
    ]

    def gh(*args):
        path = args[-1]
        if args[0] == "graphql":
            return f"{edited}\n"
        if path.endswith("/permission"):
            return json.dumps({"permission": "admin"})
        if "/events" in path:
            return json.dumps([list(events)])
        if "/comments" in path:
            return json.dumps([comments])
        return json.dumps(issue)

    monkeypatch.setattr(text, "gh", gh)


LABELED = {
    "event": "labeled",
    "label": {"name": "ready"},
    "actor": {"login": "maintainer"},
    "created_at": "2026-01-02T00:00:00Z",
}


def test_team_issue_with_trusted_comments_only(monkeypatch, capsys, text):
    fake_gh(monkeypatch, text, "MEMBER")
    text.main(["7"])
    assert json.loads(capsys.readouterr().out) == {
        "number": 7,
        "title": "t",
        "body": "b",
        "comments": [{"author": "maintainer", "body": "ok"}],
    }


def test_labeled_stranger_issue_is_printed(monkeypatch, capsys, text):
    fake_gh(monkeypatch, text, "NONE", [LABELED])
    text.main(["7"])
    assert json.loads(capsys.readouterr().out)["body"] == "b"


def test_stranger_issue_edited_after_label_is_refused(monkeypatch, capsys, text):
    fake_gh(monkeypatch, text, "NONE", [LABELED], edited="2026-01-03T00:00:00Z")
    with pytest.raises(SystemExit) as error:
        text.main(["7"])
    assert "label it again" in error.value.code
    assert capsys.readouterr().out == ""


def test_permission_lookup_failure_is_no_writer(monkeypatch, text):
    def gh(*args):
        raise subprocess.CalledProcessError(1, "gh")

    monkeypatch.setattr(text, "gh", gh)
    assert text.permission("bot") is None
