import json
import subprocess

import pytest
from conftest import copy_scripts, project, write_executable


@pytest.fixture
def run_start(tmp_path, app):
    scripts = tmp_path / "plugin" / "host"
    stubs = tmp_path / "bin"
    stubs.mkdir()
    copy_scripts(
        scripts, "autopilot-start.sh", "autopilot-name.sh", "require-project-root.sh"
    )
    tmux_args = tmp_path / "tmux_args"
    write_executable(
        stubs / "tmux",
        '[ "$1" = has-session ] && { [ "$3" = "=${RUNNING_SESSION-}" ]; exit; }; '
        f'printf "%s\\n" "$@" > {tmux_args}'
        '; shift 6; "$@"',
    )
    effort_level = tmp_path / "effort_level"
    watchdog = tmp_path / "watchdog"
    write_executable(
        stubs / "claude",
        f"""case "$1" in
  --version) echo "2.1.239 (Claude Code)" ;;
  plugin) echo telegram ;;
  *) echo "${{CLAUDE_CODE_EFFORT_LEVEL-unset}}" > {effort_level}
     echo "${{CLAUDE_CODE_RETRY_WATCHDOG-unset}}" > {watchdog} ;;
esac""",
    )
    write_executable(stubs / "loginctl", "echo yes")
    for cmd in ("gh", "bun"):
        write_executable(stubs / cmd, "exit 0")

    def run(*args, env=None, cwd=app):
        tmux_args.unlink(missing_ok=True)
        result = subprocess.run(
            [str(scripts / "autopilot-start.sh"), *args],
            cwd=cwd,
            env={
                "PATH": f"{stubs}:/usr/bin:/bin",
                "TELEGRAM_BOT_TOKEN": "t",
                **(env or {}),
            },
            check=False,
            capture_output=True,
            text=True,
        )
        lines = tmux_args.read_text().splitlines() if tmux_args.exists() else []
        return result, lines, effort_level, watchdog

    return run


@pytest.mark.parametrize(
    ("args", "prompt"),
    [((), "/pipeline:autopilot ready"), (("batch-1",), "/pipeline:autopilot batch-1")],
)
def test_starts_autopilot_with_label(run_start, args, prompt):
    result, tmux_args, *_ = run_start(*args)
    assert result.returncode == 0, result.stderr
    assert tmux_args[-1] == prompt


@pytest.mark.parametrize("args", [("batch 1",), ("batch", "1")])
def test_rejects_label_with_whitespace(run_start, args):
    result, tmux_args, *_ = run_start(*args)
    assert result.returncode == 1
    assert "whitespace" in result.stderr
    assert tmux_args == []


def test_starts_session_with_model_and_effort(run_start):
    result, tmux_args, *_ = run_start()
    assert result.returncode == 0, result.stderr
    command = " ".join(tmux_args)
    assert "--model sonnet --effort medium" in command


def test_removes_effort_level_from_session_environment(run_start):
    result, _, effort_level, _ = run_start(env={"CLAUDE_CODE_EFFORT_LEVEL": "high"})
    assert result.returncode == 0, result.stderr
    assert effort_level.read_text().strip() == "unset"


def test_starts_session_with_retry_watchdog(run_start):
    result, _, _, watchdog = run_start()
    assert result.returncode == 0, result.stderr
    assert watchdog.read_text().strip() == "1"


def test_registers_status_line_for_session_only(run_start):
    result, tmux_args, *_ = run_start()
    assert result.returncode == 0, result.stderr
    settings = json.loads(tmux_args[tmux_args.index("--settings") + 1])
    status_line = settings["statusLine"]
    assert status_line["command"].endswith("/plugin/host/autopilot-statusline.py")
    assert status_line["command"].startswith("/")
    assert status_line["refreshInterval"] == 60


def test_starts_session_named_after_repository_in_project(run_start, tmp_path):
    result, tmux_args, *_ = run_start()
    assert result.returncode == 0, result.stderr
    assert tmux_args[:6] == [
        "new-session",
        "-d",
        "-s",
        "autopilot-app",
        "-c",
        str(tmp_path / "app"),
    ]
    assert (tmp_path / "app" / ".pipeline").is_dir()


def test_two_projects_get_separate_sessions(run_start, tmp_path):
    site = project(tmp_path / "site", "https://github.com/o/site.git")
    _, app_args, *_ = run_start()
    _, site_args, *_ = run_start(cwd=site)
    assert app_args[3] == "autopilot-app"
    assert site_args[3:6] == ["autopilot-site", "-c", str(site)]


def test_rejects_subdirectory_of_project(run_start, app):
    (app / "docs").mkdir()
    result, tmux_args, *_ = run_start(cwd=app / "docs")
    assert result.returncode == 1
    assert "project root" in result.stderr
    assert tmux_args == []
    assert not (app / "docs" / ".pipeline").exists()


def test_refuses_while_old_session_runs(run_start, app):
    result, tmux_args, *_ = run_start(env={"RUNNING_SESSION": "autopilot"})
    assert result.returncode == 1
    assert "old session autopilot" in result.stderr
    assert tmux_args == []
