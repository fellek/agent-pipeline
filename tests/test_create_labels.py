import os
import subprocess

import pytest
from conftest import load_script, script_path, write_executable

SCRIPT = script_path("create-labels.sh")


@pytest.fixture
def gh(tmp_path, monkeypatch):
    """A gh stub on PATH that records its calls and keeps the labels in a file."""
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    write_executable(
        stubs / "gh",
        f"""printf '%s\\n' "$*" >> {tmp_path}/gh_calls
case "$1 $2" in
  "label list") cat {tmp_path}/labels 2>/dev/null || true ;;
  "label create") echo "$3" >> {tmp_path}/labels ;;
  *) exit 1 ;;
esac""",
    )
    monkeypatch.setenv("PATH", f"{stubs}:{os.environ['PATH']}")
    return tmp_path


def create_labels(cwd):
    return subprocess.run(
        [str(SCRIPT)], cwd=cwd, check=False, capture_output=True, text=True
    )


def created(gh):
    return (gh / "labels").read_text().splitlines()


def test_creates_status_and_selection_labels(gh):
    result = create_labels(gh)

    assert result.returncode == 0, result.stderr
    status = load_script("autopilot-poll.py").STATUS_LABELS
    assert set(created(gh)) == status | {"followup", "infrastructure"}
    assert len(created(gh)) == len(set(created(gh)))
    for name in created(gh):
        assert f"added label {name}" in result.stdout


def test_sets_color_and_description(gh):
    create_labels(gh)

    calls = (gh / "gh_calls").read_text().splitlines()
    assert (
        "label create ready --color 0e8a16 --description Ready for the autopilot"
        in calls
    )
    creates = [call for call in calls if call.startswith("label create ")]
    assert all("--color " in call and "--description " in call for call in creates)


def test_creates_only_missing_labels(gh):
    (gh / "labels").write_text("ready\nbug\n")

    result = create_labels(gh)

    assert result.returncode == 0, result.stderr
    assert created(gh).count("ready") == 1
    assert "kept label ready" in result.stdout
    assert "added label infrastructure" in result.stdout


def test_second_run_creates_nothing(gh):
    create_labels(gh)
    before = created(gh)

    result = create_labels(gh)

    assert result.returncode == 0, result.stderr
    assert created(gh) == before
    assert "added label" not in result.stdout


def test_fails_when_gh_fails(gh, tmp_path):
    write_executable(tmp_path / "stubs" / "gh", "echo 'gh: not logged in' >&2; exit 4")

    result = create_labels(gh)

    assert result.returncode != 0
    assert "not logged in" in result.stderr
