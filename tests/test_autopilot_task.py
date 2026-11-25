import subprocess
import sys

from conftest import script_path

TASK = script_path("autopilot-task.py")


def run_task(tmp_path, *command):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return subprocess.run(
        [sys.executable, TASK, "step", *command],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )


def test_keeps_output_and_exit_code(tmp_path):
    result = run_task(tmp_path, "sh", "-c", "echo out; echo err >&2; exit 3")
    tasks = tmp_path / ".pipeline" / "tasks"
    assert result.returncode == 3
    assert (tasks / "step.out").read_text() == "out\nerr\n"
    assert (tasks / "step.exit").read_text() == "3\n"
    assert not (tasks / "step.pid").exists()


def test_name_must_not_be_a_path(tmp_path):
    result = subprocess.run(
        [sys.executable, TASK, "../x", "true"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
