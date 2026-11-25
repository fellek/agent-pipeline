import datetime
import json
import shutil
import subprocess

import pytest
from conftest import script_path, write_executable

WEEK_RESET = datetime.datetime(2026, 11, 20, 4, 0, tzinfo=datetime.UTC)
NEXT_WEEK_RESET = WEEK_RESET + datetime.timedelta(days=7)


def window(percentage, reset):
    return {"used_percentage": percentage, "resets_at": int(reset.timestamp())}


@pytest.fixture
def statusline(tmp_path):
    repo = tmp_path / "app"
    plugin = tmp_path / "plugin"
    scripts = plugin / "host"
    stubs = tmp_path / "bin"
    channel = tmp_path / "home" / ".claude" / "channels" / "telegram"
    scripts.mkdir(parents=True)
    (plugin / "bin").mkdir()
    (repo / ".pipeline").mkdir(parents=True)
    stubs.mkdir()
    channel.mkdir(parents=True)
    shutil.copy(script_path("autopilot-statusline.py"), scripts)
    shutil.copy(script_path("telegram-send.py"), plugin / "bin")
    curl_calls = tmp_path / "curl_calls"
    write_executable(
        stubs / "curl",
        f'{{ printf "%s\\n" "$@"; cat; }} >> {curl_calls}; echo --- >> {curl_calls}',
    )
    (repo / ".pipeline" / "state.json").write_text(
        json.dumps({"chat_id": 42, "issue": 131, "step": "implement-issue"})
    )
    (channel / ".env").write_text("TELEGRAM_BOT_TOKEN=secret\n")

    class Statusline:
        pipeline = repo / ".pipeline"

        @property
        def calls(self):
            if not curl_calls.exists():
                return []
            return curl_calls.read_text().split("---\n")[:-1]

        def run(self, rate_limits=None, env=None, cwd=repo):
            payload = {} if rate_limits is None else {"rate_limits": rate_limits}
            return subprocess.run(
                [str(scripts / "autopilot-statusline.py")],
                cwd=cwd,
                input=json.dumps(payload),
                env={
                    "PATH": f"{stubs}:/usr/bin:/bin",
                    "HOME": str(tmp_path / "home"),
                    **(env or {}),
                },
                check=True,
                capture_output=True,
                text=True,
            ).stdout

    return Statusline()


def test_weekly_limit_sends_one_notice(statusline):
    statusline.run({"seven_day": window(100, WEEK_RESET)})
    (call,) = statusline.calls
    assert "chat_id=42" in call
    assert (
        "text=#131 implement-issue: Wochenlimit erreicht, "
        "Reset 2026-11-20 04:00 UTC, Autopilot setzt danach fort"
    ) in call


def test_session_limit_notice_names_session(statusline):
    statusline.run({"five_hour": window(100, WEEK_RESET)})
    assert "Session-Limit erreicht" in statusline.calls[0]


def test_same_reset_is_reported_once(statusline):
    limits = {"seven_day": window(100, WEEK_RESET)}
    statusline.run(limits)
    statusline.run(limits)
    assert len(statusline.calls) == 1


def test_new_reset_is_reported_again(statusline):
    statusline.run({"seven_day": window(100, WEEK_RESET)})
    statusline.run({"seven_day": window(100, NEXT_WEEK_RESET)})
    assert len(statusline.calls) == 2


def test_limit_file_records_reset(statusline):
    statusline.run({"seven_day": window(100, WEEK_RESET)})
    limit = json.loads((statusline.pipeline / "limit.json").read_text())
    assert limit == {"seven_day": "2026-11-20 04:00"}


def test_reads_and_writes_state_of_project_root_from_subdirectory(statusline):
    project = statusline.pipeline.parent
    subdirectory = project / "docs"
    subdirectory.mkdir()
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    statusline.run({"seven_day": window(100, WEEK_RESET)}, cwd=subdirectory)
    assert "chat_id=42" in statusline.calls[0]
    assert (statusline.pipeline / "limit.json").exists()
    assert not (subdirectory / ".pipeline").exists()


def test_limit_file_drops_window_that_reset(statusline):
    statusline.run(
        {"five_hour": window(100, WEEK_RESET), "seven_day": window(100, WEEK_RESET)}
    )
    statusline.run({"seven_day": window(100, WEEK_RESET)})
    limit = json.loads((statusline.pipeline / "limit.json").read_text())
    assert limit == {"seven_day": "2026-11-20 04:00"}


@pytest.mark.parametrize(
    "rate_limits",
    [None, {"seven_day": window(99.9, WEEK_RESET)}],
    ids=["none", "below"],
)
def test_below_limit_sends_nothing_and_clears_limit_file(statusline, rate_limits):
    (statusline.pipeline / "limit.json").write_text('{"seven_day": "x"}')
    statusline.run(rate_limits)
    assert statusline.calls == []
    assert not (statusline.pipeline / "limit.json").exists()


def test_failed_send_keeps_the_output_and_is_retried_once(statusline, tmp_path):
    limits = {"seven_day": window(100, WEEK_RESET)}
    curl = tmp_path / "bin" / "curl"
    write_executable(curl, f"echo x >> {tmp_path}/failed; cat > /dev/null; exit 22")

    outputs = [statusline.run(limits) for _ in range(3)]

    assert outputs == ["7d 100%\n"] * 3
    assert (tmp_path / "failed").read_text().count("x") == 2
    stored = json.loads((statusline.pipeline / "limit.json").read_text())
    assert stored == {"seven_day": "2026-11-20 04:00"}


def test_send_that_fails_once_reaches_telegram_on_the_next_run(statusline, tmp_path):
    limits = {"seven_day": window(100, WEEK_RESET)}
    curl = tmp_path / "bin" / "curl"
    original = curl.read_text()
    write_executable(curl, "cat > /dev/null; exit 22")
    statusline.run(limits)
    curl.write_text(original)

    statusline.run(limits)

    assert len(statusline.calls) == 1


def test_prints_usage_of_both_windows(statusline):
    output = statusline.run(
        {"five_hour": window(41.6, WEEK_RESET), "seven_day": window(100, WEEK_RESET)}
    )
    assert output == "5h 42% · 7d 100%\n"


def test_prints_nothing_without_rate_limits(statusline):
    assert statusline.run() == "\n"
