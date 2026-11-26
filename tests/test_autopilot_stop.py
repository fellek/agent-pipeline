import subprocess

import pytest
from conftest import copy_scripts, write_executable


@pytest.fixture
def run_stop(tmp_path, app):
    plugin = tmp_path / "plugin"
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    copy_scripts(plugin / "host", "autopilot-stop.sh", "autopilot-name.sh")
    calls = tmp_path / "calls"
    write_executable(stubs / "tmux", f'echo "tmux $*" >> {calls}')

    def run(env):
        subprocess.run(
            [str(plugin / "host" / "autopilot-stop.sh")],
            cwd=app,
            env={"PATH": f"{stubs}:/usr/bin:/bin", **env},
            check=True,
            capture_output=True,
        )
        return calls.read_text()

    return run


def test_ends_main_process_before_the_session(run_stop):
    main = subprocess.Popen(["sleep", "30"])
    try:
        calls = run_stop({"MAINPID": str(main.pid)})
        assert main.wait(timeout=5) == -15
    finally:
        main.kill()
    assert calls == "tmux kill-session -t =autopilot-app\n"


def test_ends_only_the_session_outside_systemd(run_stop):
    assert run_stop({}) == "tmux kill-session -t =autopilot-app\n"
