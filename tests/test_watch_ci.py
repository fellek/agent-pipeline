import json
import subprocess

import pytest
from conftest import load_script

RUN = {"databaseId": 7, "url": "https://example.test/runs/7"}


@pytest.fixture
def watcher(monkeypatch):
    module = load_script("watch-ci.py")
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    return module


def fake_gh(monkeypatch, listings, watch_exit=0):
    calls = []
    listings = iter(listings)

    def run(args, **kwargs):
        calls.append(args)
        if args[:3] == ["gh", "run", "list"]:
            stdout = json.dumps(next(listings))
            return subprocess.CompletedProcess(args, 0, stdout=stdout)
        return subprocess.CompletedProcess(args, watch_exit)

    monkeypatch.setattr(subprocess, "run", run)
    return calls


def test_green_run_prints_green(monkeypatch, capsys, watcher):
    calls = fake_gh(monkeypatch, [[RUN]])

    watcher.main(["master", "abc"])

    assert capsys.readouterr().out == "green\n"
    assert calls[0] == [
        "gh",
        "run",
        "list",
        "--workflow",
        "CI",
        "--branch",
        "master",
        "--commit",
        "abc",
        "--json",
        "databaseId,url",
    ]
    assert calls[1] == ["gh", "run", "watch", "7", "--exit-status"]


def test_red_run_prints_url_and_fails(monkeypatch, capsys, watcher):
    fake_gh(monkeypatch, [[RUN]], watch_exit=1)

    with pytest.raises(SystemExit) as exit_info:
        watcher.main(["master", "abc"])

    assert exit_info.value.code == 1
    assert capsys.readouterr().out == f"red {RUN['url']}\n"


def test_waits_for_run_to_appear(monkeypatch, capsys, watcher):
    calls = fake_gh(monkeypatch, [[], [], [RUN]])

    watcher.main(["master", "abc"])

    assert capsys.readouterr().out == "green\n"
    assert len(calls) == 4


def test_missing_run_after_all_attempts_fails(monkeypatch, capsys, watcher):
    calls = fake_gh(monkeypatch, [[]] * watcher.ATTEMPTS)

    with pytest.raises(SystemExit) as exit_info:
        watcher.main(["master", "abc"])

    assert exit_info.value.code == 1
    assert capsys.readouterr().out == "missing\n"
    assert len(calls) == watcher.ATTEMPTS


@pytest.mark.parametrize("argv", [[], ["master"], ["master", "abc", "extra"]])
def test_main_rejects_invalid_arguments(watcher, argv):
    with pytest.raises(SystemExit) as exit_info:
        watcher.main(argv)

    assert "Usage" in str(exit_info.value.code)
