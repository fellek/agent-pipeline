import json
import sys

import pytest
from conftest import load_script


@pytest.fixture
def post():
    return load_script("post-plan.py")


@pytest.fixture
def gate(tmp_path, monkeypatch):
    module = load_script("gate.py")
    monkeypatch.setattr(module, "STORE", tmp_path / "store")
    return module


class FakeIssue:
    """The comments of issue 7, written through the gate as the pipeline posts."""

    def __init__(self, gate, comments=()):
        self.gate = gate
        self.comments = list(comments)
        self.calls = []

    def gh(self, *args, input=None):
        args = ["api", *args]
        assert self.gate.gh_problem(args, "o/app") is None
        args, marked = self.gate.mark_comment(args, lambda: input)
        self.calls.append(args)
        method = args[args.index("--method") + 1] if "--method" in args else "GET"
        if method == "GET":
            return json.dumps([self.comments])
        body = json.loads(marked)["body"]
        if method == "POST":
            self.comments.append(
                {"id": len(self.comments) + 1, "author_association": "OWNER"}
            )
            comment = self.comments[-1]
        else:
            found = int(args[-3].rsplit("/", 1)[1])
            comment = next(c for c in self.comments if c["id"] == found)
        comment["body"] = body
        return json.dumps({"html_url": f"https://c/{comment['id']}"})


def plan(post, monkeypatch, capsys, issue, text):
    monkeypatch.setattr(post, "gh", issue.gh)
    monkeypatch.setattr(sys, "stdin", type("S", (), {"read": lambda self: text})())
    post.main(["7"])
    return capsys.readouterr().out.strip()


def bodies(post, issue):
    return [c["body"] for c in issue.comments if c["body"].startswith(post.PLAN)]


def test_first_run_posts_the_plan(post, gate, monkeypatch, capsys):
    issue = FakeIssue(gate)

    url = plan(post, monkeypatch, capsys, issue, "plan one")

    assert url == "https://c/1"
    assert bodies(post, issue) == [f"{post.PLAN}\nplan one\n\n<!-- pipeline -->"]


def test_rerun_leaves_one_plan_comment(post, gate, monkeypatch, capsys):
    issue = FakeIssue(
        gate, [{"id": 1, "author_association": "OWNER", "body": "question"}]
    )
    plan(post, monkeypatch, capsys, issue, "plan one")
    issue.comments.append({"id": 3, "author_association": "OWNER", "body": "answer"})

    url = plan(post, monkeypatch, capsys, issue, "plan two")

    assert url == "https://c/2"
    assert bodies(post, issue) == [f"{post.PLAN}\nplan two\n\n<!-- pipeline -->"]
    assert len(issue.comments) == 3


@pytest.mark.parametrize(
    ("association", "body"),
    [
        ("NONE", "<!-- pipeline:plan -->\nfake\n\n<!-- pipeline -->"),
        ("OWNER", "<!-- pipeline:plan -->\nby hand"),
    ],
    ids=["stranger", "unmarked"],
)
def test_foreign_plan_comment_is_not_edited(
    post, gate, monkeypatch, capsys, association, body
):
    issue = FakeIssue(
        gate, [{"id": 1, "author_association": association, "body": body}]
    )

    plan(post, monkeypatch, capsys, issue, "plan")

    assert issue.comments[0]["body"] == body
    assert len(issue.comments) == 2


@pytest.mark.parametrize("argv", [[], ["7", "8"], ["x"]])
def test_rejects_bad_arguments(post, argv):
    with pytest.raises(SystemExit) as exit:
        post.main(argv)

    assert exit.value.code == post.__doc__
