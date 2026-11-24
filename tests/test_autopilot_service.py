import subprocess

import pytest
from conftest import copy_scripts, write_executable


@pytest.fixture
def run_service(tmp_path, app):
    scripts = tmp_path / "scripts"
    stubs = tmp_path / "bin"
    stubs.mkdir()
    copy_scripts(scripts, "autopilot-service.sh", "autopilot-name.sh")
    write_executable(stubs / "sleep", "exit 0")
    checks = tmp_path / "checks"

    start_args = tmp_path / "start_args"

    def run(start_status=0, live_checks=0, args=()):
        write_executable(
            scripts / "autopilot-start.sh",
            f'echo "$@" > {start_args}; exit {start_status}',
        )
        write_executable(
            stubs / "tmux",
            f'echo "$*" >> {checks}; [ "$(wc -l < {checks})" -le {live_checks} ]',
        )
        result = subprocess.run(
            [str(scripts / "autopilot-service.sh"), *args],
            cwd=app,
            env={"PATH": f"{stubs}:/usr/bin:/bin"},
            check=False,
            capture_output=True,
            text=True,
        )
        return result, checks.read_text().splitlines() if checks.exists() else []

    return run


def test_fails_once_session_ends(run_service):
    result, checks = run_service(live_checks=2)
    assert result.returncode == 1
    assert checks == ["has-session -t =autopilot-app"] * 3
    assert "autopilot-app: tmux session ended" in result.stderr


def test_returns_start_script_failure(run_service):
    result, checks = run_service(start_status=3)
    assert result.returncode == 3
    assert checks == []


def test_passes_label_to_start_script(run_service, tmp_path):
    run_service(args=("batch-1",))
    assert (tmp_path / "start_args").read_text() == "batch-1\n"
