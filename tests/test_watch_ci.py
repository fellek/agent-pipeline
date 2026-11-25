import json
import subprocess

import pytest
from conftest import load_script

CI = {"databaseId": 7, "name": "CI", "url": "https://example.test/runs/7"}
INTEGRATION = {
    "databaseId": 9,
    "name": "Integration",
    "url": "https://example.test/runs/9",
}
REVIEW = {"databaseId": 3, "name": "agent-review", "url": "https://example.test/runs/3"}
RULES = "## Checks\n\n```\nx\n```\n\nRequired workflows: CI, Integration\n"


@pytest.fixture
def watcher(monkeypatch, tmp_path):
    module = load_script("watch-ci.py")
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(module, "default_branch", lambda: "main")
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".claude" / "rules").mkdir(parents=True)
    (tmp_path / ".claude" / "rules" / "project.md").write_text(RULES)
    return module


def fake_gh(monkeypatch, listings, watch_exits=(0, 0)):
    calls = []
    listings = iter(listings)
    watch_exits = iter(watch_exits)

    def run(args, **kwargs):
        calls.append(args)
        if args[:3] == ["gh", "run", "list"]:
            stdout = json.dumps(next(listings))
            return subprocess.CompletedProcess(args, 0, stdout=stdout)
        return subprocess.CompletedProcess(args, next(watch_exits))

    monkeypatch.setattr(subprocess, "run", run)
    return calls


def test_green_runs_print_green(monkeypatch, capsys, watcher):
    calls = fake_gh(monkeypatch, [[INTEGRATION, CI, REVIEW]])
    watcher.main(["issue-1-x", "abc"])
    assert capsys.readouterr().out == "green\n"
    assert calls[0] == [
        "gh",
        "run",
        "list",
        "--branch",
        "issue-1-x",
        "--commit",
        "abc",
        "--limit",
        "100",
        "--json",
        "databaseId,name,url",
    ]
    assert calls[1:] == [
        ["gh", "run", "watch", "9", "--exit-status"],
        ["gh", "run", "watch", "7", "--exit-status"],
    ]


def test_late_required_workflow_is_awaited(monkeypatch, capsys, watcher):
    calls = fake_gh(monkeypatch, [[CI], [CI], [INTEGRATION, CI]])
    watcher.main(["issue-1-x", "abc"])
    assert capsys.readouterr().out == "green\n"
    assert len([c for c in calls if c[:3] == ["gh", "run", "list"]]) == 3


def test_missing_required_workflow_prints_missing(monkeypatch, capsys, watcher):
    fake_gh(monkeypatch, [[CI]] * watcher.ATTEMPTS)
    with pytest.raises(SystemExit):
        watcher.main(["issue-1-x", "abc"])
    assert capsys.readouterr().out == "missing\n"


def test_default_branch_takes_the_runs_it_finds(monkeypatch, capsys, watcher):
    fake_gh(monkeypatch, [[CI]], watch_exits=[0])
    watcher.main(["main", "abc"])
    assert capsys.readouterr().out == "green\n"


def test_red_run_prints_its_url_and_fails(monkeypatch, capsys, watcher):
    calls = fake_gh(monkeypatch, [[CI, INTEGRATION]], watch_exits=[1])
    with pytest.raises(SystemExit) as exit_info:
        watcher.main(["issue-1-x", "abc"])
    assert exit_info.value.code == 1
    assert capsys.readouterr().out == f"red {CI['url']}\n"
    assert len(calls) == 2


def test_only_the_latest_run_of_a_workflow_counts(monkeypatch, capsys, watcher):
    old = {**CI, "databaseId": 5}
    calls = fake_gh(monkeypatch, [[CI, old, INTEGRATION]])
    watcher.main(["issue-1-x", "abc"])
    assert ["gh", "run", "watch", "5", "--exit-status"] not in calls


def test_no_run_prints_missing(monkeypatch, capsys, watcher):
    fake_gh(monkeypatch, [[]] * watcher.ATTEMPTS)
    with pytest.raises(SystemExit):
        watcher.main(["main", "abc"])
    assert capsys.readouterr().out == "missing\n"


def test_deadline_prints_timeout(monkeypatch, capsys, watcher):
    def run(args, **kwargs):
        if args[:3] == ["gh", "run", "list"]:
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps([CI]))
        raise subprocess.TimeoutExpired(args, 0)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(SystemExit):
        watcher.main(["main", "abc"])
    assert capsys.readouterr().out == "timeout\n"


@pytest.mark.parametrize(
    ("text", "names"),
    [
        (RULES, ["CI", "Integration"]),
        ("## Checks\n\n```\nx\n```\n", []),
        ("## Other\n\nRequired workflows: X\n\n## Checks\n", []),
    ],
)
def test_required_workflows_come_from_the_checks_section(watcher, text, names):
    assert watcher.required_workflows(text) == names


@pytest.mark.parametrize("argv", [[], ["master"], ["master", "abc", "extra"]])
def test_main_rejects_invalid_arguments(watcher, argv):
    with pytest.raises(SystemExit) as exit_info:
        watcher.main(argv)

    assert "Usage" in str(exit_info.value.code)
