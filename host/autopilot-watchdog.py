#!/usr/bin/env python3
"""Report a failed or stuck autopilot via Telegram, from systemd units.

`failed` runs on OnFailure= of the service: systemd restarts it with a growing
delay, so each message is one failed start. `check` runs from a timer: it reports
a state unchanged for 3 hours while a step runs, and a prompt in the tmux
session (a permission prompt the Telegram plugin did not get through). It sends
each finding once, until it changes.

Usage:
  autopilot-watchdog.py failed|check
"""

import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

HOST = Path(__file__).resolve().parent
TELEGRAM = HOST.parent / "bin" / "telegram-send.py"
PIPELINE = Path(".pipeline")
STALE_SECONDS = 3 * 3600
# Waiting for the maintainer or a new issue is no sign of a stuck session.
IDLE = {"new_issue", "resume", "restart"}
PROMPT = re.compile(r"Do you want to ")
PANE_LINES = 20


def session():
    return subprocess.run(
        [HOST / "autopilot-name.sh"], capture_output=True, text=True, check=True
    ).stdout.strip()


def send(text):
    subprocess.run([TELEGRAM], input=text, text=True, check=True)


def stale(now):
    path = PIPELINE / "state.json"
    if not path.exists():
        return None
    age = now - path.stat().st_mtime
    waiting = json.loads(path.read_text()).get("waiting_for")
    if age < STALE_SECONDS or waiting in IDLE:
        return None
    hours = f"{age / 3600:.0f} h"
    text = f"Zustand seit {hours} unverändert (wartet auf {waiting}), bitte prüfen"
    return f"stale {path.stat().st_mtime}", text


def prompt(name):
    pane = subprocess.run(
        ["tmux", "capture-pane", "-p", "-t", f"={name}"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    tail = "\n".join(pane.rstrip().splitlines()[-PANE_LINES:])
    match = PROMPT.search(tail)
    if not match:
        return None
    # The rest of the pane keeps changing (spinner, timer), the question does not.
    question = tail[match.start() :].splitlines()[0]
    digest = hashlib.sha256(question.encode()).hexdigest()
    return f"prompt {digest}", f"Session wartet auf eine Eingabe:\n{tail}"


def check(now):
    name = session()
    memory = PIPELINE / "watchdog.json"
    alerted = json.loads(memory.read_text()) if memory.exists() else []
    findings = [f for f in (stale(now), prompt(name)) if f]
    sent = [key for key, _ in findings if key in alerted]
    PIPELINE.mkdir(exist_ok=True)
    for key, text in findings:
        if key not in sent:
            send(f"{name}: {text}")
            # A later failed send must not repeat this one.
            sent.append(key)
            memory.write_text(json.dumps(sent))
    memory.write_text(json.dumps(sent))


def main(argv):
    match argv:
        case ["failed"]:
            name = session()
            send(
                f"{name}: Dienst fehlgeschlagen, systemd startet ihn neu "
                f"(journalctl --user -u {name})"
            )
        case ["check"]:
            check(time.time())
        case _:
            sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
