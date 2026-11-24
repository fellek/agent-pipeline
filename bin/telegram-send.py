#!/usr/bin/env python3
"""Send the text from stdin to the maintainer via Telegram.

Each argument becomes a button of a reply keyboard; pressing one sends its
label as a message. The Telegram plugin of the autopilot session only offers
buttons for permission prompts, so this calls the Bot API directly.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

# State of the project in the working directory, not of the plugin.
PIPELINE = Path(".pipeline")
CHANNEL = Path.home() / ".claude" / "channels" / "telegram"


def read_json(path):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}


def telegram_token():
    if token := os.environ.get("TELEGRAM_BOT_TOKEN"):
        return token
    for line in (CHANNEL / ".env").read_text().splitlines():
        key, _, value = line.partition("=")
        if key == "TELEGRAM_BOT_TOKEN":
            return value.strip()
    raise SystemExit("Telegram token is missing")


def telegram_chat_id():
    state = read_json(PIPELINE / "state.json")
    return state.get("chat_id") or read_json(CHANNEL / "access.json")["allowFrom"][0]


def reply_keyboard(buttons):
    return json.dumps(
        {
            "keyboard": [[{"text": button} for button in buttons]],
            "resize_keyboard": True,
            "one_time_keyboard": True,
        }
    )


def send(text, buttons):
    # The token goes through stdin so it stays out of the process list.
    config = f'url = "https://api.telegram.org/bot{telegram_token()}/sendMessage"\n'
    fields = {"chat_id": telegram_chat_id(), "text": text}
    if buttons:
        fields["reply_markup"] = reply_keyboard(buttons)
    subprocess.run(
        [
            "curl",
            "--silent",
            "--fail",
            "--max-time",
            "5",
            "--config",
            "-",
            *[
                argument
                for name, value in fields.items()
                for argument in ("--data-urlencode", f"{name}={value}")
            ],
        ],
        input=config,
        text=True,
        check=True,
        stdout=subprocess.DEVNULL,
    )


if __name__ == "__main__":
    send(sys.stdin.read().strip(), sys.argv[1:])
