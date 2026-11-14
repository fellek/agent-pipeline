import shutil
import subprocess

import pytest
from conftest import SCRIPTS, write_executable


@pytest.fixture
def run_status(tmp_path):
    repo = tmp_path / "repo"
    scripts = repo / ".github" / "scripts"
    stubs = tmp_path / "bin"
    scripts.mkdir(parents=True)
    (repo / ".pipeline").mkdir()
    stubs.mkdir()
    shutil.copy(SCRIPTS / "autopilot-status.sh", scripts)
    for cmd in ("tmux", "systemctl"):
        write_executable(stubs / cmd, "exit 1")

    def run():
        return subprocess.run(
            [str(scripts / "autopilot-status.sh")],
            env={"PATH": f"{stubs}:/usr/bin:/bin"},
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    return repo, run


def test_prints_limit_file(run_status):
    repo, run = run_status
    (repo / ".pipeline" / "limit.json").write_text('{"seven_day": "2026-11-20 04:00"}')
    assert '--- limit\n{"seven_day": "2026-11-20 04:00"}' in run()


def test_prints_none_without_limit_file(run_status):
    _, run = run_status
    assert "--- limit\n(none)\n" in run()
