import subprocess

import pytest
from conftest import project, script_path

SCRIPT = script_path("autopilot-name.sh")


def name(cwd):
    return subprocess.run(
        [str(SCRIPT)],
        cwd=cwd,
        env={"PATH": "/usr/bin:/bin"},
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        ("git@github.com:fellek/agent-pipeline.git", "autopilot-agent-pipeline"),
        ("https://github.com/fellek/agent-pipeline", "autopilot-agent-pipeline"),
        ("https://github.com/fellek/agent-pipeline/", "autopilot-agent-pipeline"),
        ("https://github.com/fellek/my.site.git", "autopilot-my-site"),
    ],
)
def test_name_from_origin_url(tmp_path, origin, expected):
    assert name(project(tmp_path / "checkout", origin)) == expected


def test_name_from_directory_without_git(tmp_path):
    folder = tmp_path / "some.project"
    folder.mkdir()
    assert name(folder) == "autopilot-some-project"
