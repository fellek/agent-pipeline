import subprocess

import pytest
from conftest import copy_scripts, write_executable


@pytest.fixture
def run_status(tmp_path, app):
    repo = app
    scripts = tmp_path / "plugin" / "host"
    stubs = tmp_path / "bin"
    (repo / ".pipeline").mkdir()
    stubs.mkdir()
    copy_scripts(
        scripts, "autopilot-status.sh", "autopilot-name.sh", "require-project-root.sh"
    )
    write_executable(stubs / "tmux", "exit 1")
    write_executable(stubs / "systemctl", 'echo "$*"; exit 3')

    def run(cwd=repo, check=True):
        result = subprocess.run(
            [str(scripts / "autopilot-status.sh")],
            cwd=cwd,
            env={"PATH": f"{stubs}:/usr/bin:/bin"},
            check=check,
            capture_output=True,
            text=True,
        )
        return result.stdout if check else result

    return repo, run


def test_prints_limit_file(run_status):
    repo, run = run_status
    (repo / ".pipeline" / "limit.json").write_text('{"seven_day": "2026-11-20 04:00"}')
    assert '--- limit\n{"seven_day": "2026-11-20 04:00"}' in run()


def test_prints_none_without_limit_file(run_status):
    _, run = run_status
    assert "--- limit\n(none)\n" in run()


def test_queries_service_of_project(run_status):
    _, run = run_status
    assert "service: --user is-active autopilot-app.service\n" in run()


def test_rejects_subdirectory_of_project(run_status):
    repo, run = run_status
    (repo / "docs").mkdir()
    result = run(cwd=repo / "docs", check=False)
    assert result.returncode == 1
    assert "project root" in result.stderr
    assert result.stdout == ""
