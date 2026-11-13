import shutil
import subprocess

import pytest
from conftest import SCRIPTS, write_executable


@pytest.fixture
def run_start(tmp_path):
    scripts = tmp_path / "repo" / ".github" / "scripts"
    stubs = tmp_path / "bin"
    scripts.mkdir(parents=True)
    stubs.mkdir()
    shutil.copy(SCRIPTS / "autopilot-start.sh", scripts)
    tmux_args = tmp_path / "tmux_args"
    write_executable(
        stubs / "tmux",
        f'[ "$1" = has-session ] && exit 1; printf "%s\\n" "$@" > {tmux_args}',
    )
    write_executable(
        stubs / "claude",
        '[ "$1" = --version ] && echo "2.1.80 (Claude Code)" || echo telegram',
    )
    write_executable(stubs / "loginctl", "echo yes")
    for cmd in ("git", "gh", "bun", "uv"):
        write_executable(stubs / cmd, "exit 0")

    def run(*args):
        result = subprocess.run(
            [str(scripts / "autopilot-start.sh"), *args],
            env={"PATH": f"{stubs}:/usr/bin:/bin", "TELEGRAM_BOT_TOKEN": "t"},
            check=False,
            capture_output=True,
            text=True,
        )
        lines = tmux_args.read_text().splitlines() if tmux_args.exists() else []
        return result, lines

    return run


@pytest.mark.parametrize(
    ("args", "prompt"),
    [((), "/autopilot ready"), (("batch-1",), "/autopilot batch-1")],
)
def test_starts_autopilot_with_label(run_start, args, prompt):
    result, tmux_args = run_start(*args)
    assert result.returncode == 0, result.stderr
    assert tmux_args[-1] == prompt


@pytest.mark.parametrize("args", [("batch 1",), ("batch", "1")])
def test_rejects_label_with_whitespace(run_start, args):
    result, tmux_args = run_start(*args)
    assert result.returncode == 1
    assert "whitespace" in result.stderr
    assert tmux_args == []
