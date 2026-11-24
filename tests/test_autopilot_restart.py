import shutil
import subprocess

import pytest
from conftest import script_path, write_executable

IS_ACTIVE = "systemctl --user is-active --quiet autopilot\n"
RESET_FAILED = "systemctl --user reset-failed autopilot\n"


@pytest.fixture
def run_restart(tmp_path):
    plugin = tmp_path / "plugin"
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for folder, script in (
        ("bin", "autopilot-restart.sh"),
        ("host", "autopilot-stop.sh"),
    ):
        (plugin / folder).mkdir(parents=True)
        shutil.copy(script_path(script), plugin / folder)
    calls = tmp_path / "calls"
    write_executable(stubs / "tmux", f'echo "tmux $*" >> {calls}')

    def run(service_status):
        write_executable(
            stubs / "systemctl",
            f'echo "systemctl $*" >> {calls}; exit {service_status}',
        )
        result = subprocess.run(
            [str(plugin / "bin" / "autopilot-restart.sh")],
            env={"PATH": f"{stubs}:/usr/bin:/bin", "XDG_RUNTIME_DIR": str(tmp_path)},
            check=False,
            capture_output=True,
            text=True,
        )
        return result, calls.read_text() if calls.exists() else ""

    return run


def test_ends_session_when_service_is_active(run_restart):
    result, calls = run_restart(service_status=0)
    assert result.returncode == 0
    assert calls == f"{IS_ACTIVE}{RESET_FAILED}tmux kill-session -t autopilot\n"


def test_fails_without_active_service(run_restart):
    result, calls = run_restart(service_status=3)
    assert result.returncode != 0
    assert calls == IS_ACTIVE
