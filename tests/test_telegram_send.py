import json
import shutil
import subprocess

import pytest
from conftest import script_path, write_executable


@pytest.fixture
def telegram(tmp_path):
    repo = tmp_path / "app"
    scripts = tmp_path / "plugin" / "bin"
    stubs = tmp_path / "bin"
    channel = tmp_path / "home" / ".claude" / "channels" / "telegram"
    scripts.mkdir(parents=True)
    (repo / ".pipeline").mkdir(parents=True)
    stubs.mkdir()
    channel.mkdir(parents=True)
    shutil.copy(script_path("telegram-send.py"), scripts)
    arguments_file = tmp_path / "curl_arguments"
    config_file = tmp_path / "curl_config"
    write_executable(
        stubs / "curl", f'printf "%s\\0" "$@" > {arguments_file}; cat > {config_file}'
    )
    (repo / ".pipeline" / "state.json").write_text('{"chat_id": 42}')
    (channel / ".env").write_text("TELEGRAM_BOT_TOKEN=secret\n")

    class Telegram:
        state = repo / ".pipeline" / "state.json"
        access = channel / "access.json"
        env_file = channel / ".env"

        @property
        def arguments(self):
            return arguments_file.read_text().split("\0")[:-1]

        @property
        def config(self):
            return config_file.read_text()

        @property
        def fields(self):
            arguments = self.arguments
            return dict(
                arguments[i + 1].split("=", 1)
                for i, argument in enumerate(arguments)
                if argument == "--data-urlencode"
            )

        def run(self, text, *buttons, env=None):
            return subprocess.run(
                [str(scripts / "telegram-send.py"), *buttons],
                cwd=repo,
                input=text,
                env={
                    "PATH": f"{stubs}:/usr/bin:/bin",
                    "HOME": str(tmp_path / "home"),
                    **(env or {}),
                },
                check=True,
                capture_output=True,
                text=True,
            )

    return Telegram()


def test_sends_stdin_text_to_chat_of_state(telegram):
    telegram.run("#7 Frage\n1. a) x b) y\n")
    assert telegram.fields == {"chat_id": "42", "text": "#7 Frage\n1. a) x b) y"}


def test_buttons_become_one_time_reply_keyboard(telegram):
    telegram.run("#7 Frage", "#7 a", "#7 b")
    assert json.loads(telegram.fields["reply_markup"]) == {
        "keyboard": [[{"text": "#7 a"}, {"text": "#7 b"}]],
        "resize_keyboard": True,
        "one_time_keyboard": True,
    }


def test_without_buttons_no_keyboard_is_sent(telegram):
    telegram.run("#7 fertig")
    assert "reply_markup" not in telegram.fields


def test_chat_id_falls_back_to_access_file(telegram):
    telegram.state.write_text('{"chat_id": null}')
    telegram.access.write_text('{"allowFrom": ["7", "8"]}')
    telegram.run("x")
    assert telegram.fields["chat_id"] == "7"


def test_token_stays_out_of_arguments(telegram):
    telegram.run("x")
    assert "secret" not in "".join(telegram.arguments)
    assert "bot" + "secret/sendMessage" in telegram.config


def test_token_from_environment_wins(telegram):
    telegram.run("x", env={"TELEGRAM_BOT_TOKEN": "env"})
    assert "botenv/sendMessage" in telegram.config


def test_missing_token_fails(telegram):
    telegram.env_file.write_text("")
    with pytest.raises(subprocess.CalledProcessError) as error:
        telegram.run("x")
    assert "Telegram token is missing" in error.value.stderr


def test_failed_request_fails(telegram, tmp_path):
    write_executable(tmp_path / "bin" / "curl", "exit 22")
    with pytest.raises(subprocess.CalledProcessError):
        telegram.run("x")
