#!/usr/bin/env python3
"""Status line command of the autopilot session.

Reads the session JSON from stdin, prints the rate limit usage and sends a
Telegram notice once per reset time when a window is exhausted. Runs on a
timer, so it also fires while a request waits for a limit to reset.
"""

import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

PIPELINE = Path(__file__).parents[2] / ".pipeline"
CHANNEL = Path.home() / ".claude" / "channels" / "telegram"
WINDOWS = {"five_hour": ("5h", "Session-Limit"), "seven_day": ("7d", "Wochenlimit")}


def read_json(path):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}


def exhausted_windows(rate_limits):
    return {
        name: datetime.datetime.fromtimestamp(
            window["resets_at"], datetime.UTC
        ).strftime("%Y-%m-%d %H:%M")
        for name, window in rate_limits.items()
        if name in WINDOWS and window["used_percentage"] >= 100
    }


def telegram_token():
    if token := os.environ.get("TELEGRAM_BOT_TOKEN"):
        return token
    for line in (CHANNEL / ".env").read_text().splitlines():
        key, _, value = line.partition("=")
        if key == "TELEGRAM_BOT_TOKEN":
            return value.strip()
    raise SystemExit("Telegram token is missing")


def telegram_chat_id(state):
    return state.get("chat_id") or read_json(CHANNEL / "access.json")["allowFrom"][0]


def notify(text, state):
    # The token goes through stdin so it stays out of the process list.
    config = f'url = "https://api.telegram.org/bot{telegram_token()}/sendMessage"\n'
    subprocess.run(
        [
            "curl",
            "--silent",
            "--fail",
            "--max-time",
            "5",
            "--config",
            "-",
            "--data-urlencode",
            f"chat_id={telegram_chat_id(state)}",
            "--data-urlencode",
            f"text={text}",
        ],
        input=config,
        text=True,
        check=True,
        stdout=subprocess.DEVNULL,
    )


def notice(state, name, resets_at):
    prefix = f"#{state['issue']} {state['step']}: " if state.get("issue") else ""
    return (
        f"{prefix}{WINDOWS[name][1]} erreicht, Reset {resets_at} UTC, "
        "Autopilot setzt danach fort"
    )


def main():
    rate_limits = json.load(sys.stdin).get("rate_limits", {})
    limit_file = PIPELINE / "limit.json"
    exhausted = exhausted_windows(rate_limits)
    stored = read_json(limit_file)
    reported = {name: reset for name, reset in stored.items() if name in exhausted}
    state = read_json(PIPELINE / "state.json")
    for name, resets_at in exhausted.items():
        if reported.get(name) != resets_at:
            notify(notice(state, name, resets_at), state)
            reported[name] = resets_at
    if not reported:
        limit_file.unlink(missing_ok=True)
    elif reported != stored:
        limit_file.write_text(json.dumps(reported))
    print(
        " · ".join(
            f"{label} {window['used_percentage']:.0f}%"
            for name, (label, _) in WINDOWS.items()
            if (window := rate_limits.get(name))
        )
    )


if __name__ == "__main__":
    main()
