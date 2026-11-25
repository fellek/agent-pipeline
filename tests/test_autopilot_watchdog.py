import json
import os
import subprocess

import pytest
from conftest import load_script

NOW = 1_800_000_000


@pytest.fixture
def watchdog(tmp_path, monkeypatch):
    module = load_script("autopilot-watchdog.py")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module, "session", lambda: "autopilot-app")
    sent = []
    monkeypatch.setattr(module, "send", sent.append)
    module.sent = sent
    module.pane = ""

    def run(args, **kwargs):
        assert args[:2] == ["tmux", "capture-pane"]
        return subprocess.CompletedProcess(args, 0, stdout=module.pane)

    monkeypatch.setattr(module.subprocess, "run", run)
    return module


def write_state(waiting_for, age_hours):
    path = os.path.join(".pipeline", "state.json")
    os.makedirs(".pipeline", exist_ok=True)
    with open(path, "w") as state:
        json.dump({"waiting_for": waiting_for}, state)
    mtime = NOW - age_hours * 3600
    os.utime(path, (mtime, mtime))


def test_stale_running_step_is_reported_once(watchdog):
    write_state("step", 4)

    watchdog.check(NOW)
    watchdog.check(NOW + 900)

    assert watchdog.sent == [
        "autopilot-app: Zustand seit 4 h unverändert (wartet auf step), bitte prüfen"
    ]


@pytest.mark.parametrize("waiting_for", ["new_issue", "resume", "restart"])
def test_waiting_for_the_maintainer_is_no_finding(watchdog, waiting_for):
    write_state(waiting_for, 10)
    watchdog.check(NOW)
    assert watchdog.sent == []


def test_recent_state_is_no_finding(watchdog):
    write_state("step", 1)
    watchdog.check(NOW)
    assert watchdog.sent == []


def test_prompt_in_the_session_is_reported_until_it_changes(watchdog):
    watchdog.pane = "output\nDo you want to proceed?\n❯ 1. Yes\n"

    watchdog.check(NOW)
    watchdog.check(NOW)
    watchdog.pane = "other\nDo you want to make this edit?\n"
    watchdog.check(NOW)

    assert len(watchdog.sent) == 2
    assert watchdog.sent[0].startswith(
        "autopilot-app: Session wartet auf eine Eingabe:"
    )
    assert "Do you want to proceed?" in watchdog.sent[0]


def test_prompt_is_not_repeated_when_the_rest_of_the_pane_changes(watchdog):
    watchdog.pane = "12s\nDo you want to proceed?\n"
    watchdog.check(NOW)
    watchdog.pane = "13s\nDo you want to proceed?\n"
    watchdog.check(NOW)
    assert len(watchdog.sent) == 1


def test_a_failed_send_does_not_repeat_the_sent_finding(watchdog, monkeypatch):
    write_state("step", 4)
    watchdog.pane = "Do you want to proceed?"

    def send(text):
        if "Eingabe" in text:
            raise subprocess.CalledProcessError(1, "telegram-send.py")
        watchdog.sent.append(text)

    monkeypatch.setattr(watchdog, "send", send)
    with pytest.raises(subprocess.CalledProcessError):
        watchdog.check(NOW)
    monkeypatch.setattr(watchdog, "send", watchdog.sent.append)
    watchdog.check(NOW)

    assert len(watchdog.sent) == 2
    assert "Eingabe" in watchdog.sent[1]


def test_a_finding_that_clears_is_reported_again_later(watchdog):
    watchdog.pane = "Do you want to proceed?"
    watchdog.check(NOW)
    watchdog.pane = "working"
    watchdog.check(NOW)
    watchdog.pane = "Do you want to proceed?"
    watchdog.check(NOW)
    assert len(watchdog.sent) == 2


def test_failed_names_the_journal(watchdog):
    watchdog.main(["failed"])
    journal = "(journalctl --user -u autopilot-app)"
    assert watchdog.sent == [
        f"autopilot-app: Dienst fehlgeschlagen, systemd startet ihn neu {journal}"
    ]


@pytest.mark.parametrize("argv", [[], ["check", "x"], ["other"]])
def test_rejects_invalid_arguments(watchdog, argv):
    with pytest.raises(SystemExit):
        watchdog.main(argv)
