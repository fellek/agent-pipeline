import shutil
import subprocess

import pytest
from conftest import SCRIPTS


def write_executable(path, body):
    path.write_text(f"#!/usr/bin/env bash\n{body}\n")
    path.chmod(0o755)


@pytest.fixture
def run_service(tmp_path):
    scripts = tmp_path / "scripts"
    stubs = tmp_path / "bin"
    scripts.mkdir()
    stubs.mkdir()
    shutil.copy(SCRIPTS / "autopilot-service.sh", scripts)
    write_executable(stubs / "sleep", "exit 0")
    checks = tmp_path / "checks"

    def run(start_status=0, live_checks=0):
        write_executable(scripts / "autopilot-start.sh", f"exit {start_status}")
        write_executable(
            stubs / "tmux",
            f'echo >> {checks}; [ "$(wc -l < {checks})" -le {live_checks} ]',
        )
        result = subprocess.run(
            [str(scripts / "autopilot-service.sh")],
            env={"PATH": f"{stubs}:/usr/bin:/bin"},
            check=False,
            capture_output=True,
            text=True,
        )
        return result, checks.read_text().count("\n") if checks.exists() else 0

    return run


def test_fails_once_session_ends(run_service):
    result, checks = run_service(live_checks=2)
    assert result.returncode == 1
    assert checks == 3


def test_returns_start_script_failure(run_service):
    result, checks = run_service(start_status=3)
    assert result.returncode == 3
    assert checks == 0
