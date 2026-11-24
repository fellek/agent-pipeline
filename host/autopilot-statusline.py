#!/usr/bin/env python3
"""Status line command of the autopilot session.

Reads the session JSON from stdin, prints the rate limit usage and sends a
Telegram notice once per reset time when a window is exhausted. Runs on a
timer, so it also fires while a request waits for a limit to reset.
"""

import datetime
import json
import subprocess
import sys
from pathlib import Path

# State of the project in the working directory, not of the plugin.
PIPELINE = Path(".pipeline")
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


def notify(text):
    subprocess.run(
        [Path(__file__).parents[1] / "bin" / "telegram-send.py"],
        input=text,
        text=True,
        check=True,
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
            notify(notice(state, name, resets_at))
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
