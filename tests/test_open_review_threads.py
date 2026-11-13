import json
import subprocess

import pytest
from conftest import load_script


@pytest.fixture
def gate():
    return load_script("open-review-threads.py")


def thread(url, resolved=False):
    return {
        "isResolved": resolved,
        "path": "a.py",
        "line": 3,
        "comments": {"nodes": [{"url": url}]},
    }


def page(*threads):
    return {
        "data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": threads}}}}
    }


def fake_gh(monkeypatch, pages):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(pages))

    monkeypatch.setattr(subprocess, "run", run)
    return calls


def test_returns_unresolved_threads_across_pages(monkeypatch, gate):
    fake_gh(monkeypatch, [page(thread("u1"), thread("r", True)), page(thread("u2"))])

    assert gate.unresolved(gate.threads(66)) == [
        {"url": "u1", "path": "a.py", "line": 3},
        {"url": "u2", "path": "a.py", "line": 3},
    ]


@pytest.mark.parametrize(
    "pages", [[page()], [page(thread("r", True))]], ids=["none", "all_resolved"]
)
def test_main_prints_empty_list(monkeypatch, capsys, gate, pages):
    fake_gh(monkeypatch, pages)

    gate.main(["66"])

    assert json.loads(capsys.readouterr().out) == []


def test_main_prints_unresolved(monkeypatch, capsys, gate):
    fake_gh(monkeypatch, [page(thread("u1"))])

    gate.main(["66"])

    assert json.loads(capsys.readouterr().out) == [
        {"url": "u1", "path": "a.py", "line": 3}
    ]


def test_queries_review_threads_with_pagination(monkeypatch, gate):
    calls = fake_gh(monkeypatch, [page()])

    gate.threads(66)

    args = calls[0]
    assert args[:5] == ["gh", "api", "graphql", "--paginate", "--slurp"]
    assert "pr=66" in args
    query = args[-1]
    assert "$endCursor" in query
    assert "reviewThreads" in query
    assert "isResolved" in query


def test_gh_failure_raises(monkeypatch, gate):
    def run(args, **kwargs):
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(subprocess, "run", run)

    with pytest.raises(subprocess.CalledProcessError):
        gate.main(["66"])


@pytest.mark.parametrize("argv", [[], ["66", "extra"]])
def test_main_rejects_invalid_arguments(gate, argv):
    with pytest.raises(SystemExit) as exit_info:
        gate.main(argv)

    assert "Usage" in str(exit_info.value.code)
