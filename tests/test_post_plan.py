import json

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


def plan(post, monkeypatch, capsys, issue, text, tmp_path):
    monkeypatch.setattr(post, "gh", issue.gh)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".pipeline").mkdir(exist_ok=True)
    (tmp_path / ".pipeline" / "plan.md").write_text(text)
    post.main(["7", ".pipeline/plan.md"])
    return capsys.readouterr().out.strip()


def bodies(post, issue):
    return [c["body"] for c in issue.comments if c["body"].startswith(post.PLAN)]


def test_first_run_posts_the_plan(post, gate, monkeypatch, capsys, tmp_path):
    issue = FakeIssue(gate)

    url = plan(post, monkeypatch, capsys, issue, "plan one", tmp_path)

    assert url == "https://c/1"
    assert bodies(post, issue) == [f"{post.PLAN}\nplan one\n\n<!-- pipeline -->"]


def test_rerun_leaves_one_plan_comment(post, gate, monkeypatch, capsys, tmp_path):
    issue = FakeIssue(
        gate, [{"id": 1, "author_association": "OWNER", "body": "question"}]
    )
    plan(post, monkeypatch, capsys, issue, "plan one", tmp_path)
    issue.comments.append({"id": 3, "author_association": "OWNER", "body": "answer"})

    url = plan(post, monkeypatch, capsys, issue, "plan two", tmp_path)

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
    post, gate, monkeypatch, capsys, association, body, tmp_path
):
    issue = FakeIssue(
        gate, [{"id": 1, "author_association": association, "body": body}]
    )

    plan(post, monkeypatch, capsys, issue, "plan", tmp_path)

    assert issue.comments[0]["body"] == body
    assert len(issue.comments) == 2


@pytest.mark.parametrize("argv", [[], ["7"], ["x", "p"], ["7", "p", "q"]])
def test_rejects_bad_arguments(post, argv):
    with pytest.raises(SystemExit) as exit:
        post.main(argv)

    assert exit.value.code == post.__doc__


@pytest.mark.parametrize("name", ["outside", "link"])
def test_reads_only_a_file_under_pipeline(post, tmp_path, monkeypatch, name):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".pipeline").mkdir()
    secret = tmp_path / "secret"
    secret.write_text("token")
    path = secret
    if name == "link":
        path = tmp_path / ".pipeline" / "plan.md"
        path.symlink_to(secret)
    with pytest.raises(SystemExit) as exit:
        post.main(["7", str(path)])
    assert "no file under .pipeline/" in exit.value.code
