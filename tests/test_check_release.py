import json
import shutil
import subprocess

import pytest
from conftest import ROOT, commit, git, script_path

SCRIPT = script_path("check-release.sh")
SUB = ".claude/skills/pipeline"
PIN = ".claude/pipeline-release"
HOOK = json.loads((ROOT / "templates" / "claude" / "settings.json").read_text())[
    "hooks"
]["SessionStart"][0]["hooks"][0]["command"]


@pytest.fixture
def plugin(tmp_path, git_identity):
    """A pipeline repository with the releases v1 and v2, both holding the script."""
    path = tmp_path / "plugin"
    path.mkdir()
    git(path, "init", "-q")
    (path / "host").mkdir()
    shutil.copy(SCRIPT, path / "host")
    git(path, "add", "host")
    tags = {}
    for tag in ("v1", "v2"):
        tags[tag] = commit(path, f"host/{tag}", tag)
        git(path, "tag", tag)
    return path, tags


@pytest.fixture
def own(plugin):
    """The pipeline repository itself, pinned to v1 and with its release worktree."""
    path, tags = plugin
    (path / ".claude").mkdir()
    (path / PIN).write_text("v1\n")
    git(path, "worktree", "add", "-q", "--detach", SUB, "v1")
    return path, tags


@pytest.fixture
def project(tmp_path, plugin):
    """A project with the pipeline as submodule at v1."""
    source, tags = plugin
    path = tmp_path / "project"
    path.mkdir()
    git(path, "init", "-q")
    git(
        path,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        str(source),
        SUB,
    )
    git(path / SUB, "checkout", "-q", "--detach", "v1")
    git(path, "add", SUB)
    git(path, "commit", "-qm", "pipeline")
    return path, tags


def check(cwd):
    return subprocess.run(
        [str(SCRIPT)], cwd=cwd, check=False, capture_output=True, text=True
    )


def run_hook(cwd):
    return subprocess.run(
        ["sh", "-c", HOOK],
        cwd="/",
        env={"CLAUDE_PROJECT_DIR": str(cwd), "PATH": "/usr/bin:/bin"},
        check=False,
        capture_output=True,
        text=True,
    )


def assert_warns(result, text):
    assert result.returncode == 1
    assert result.stdout.startswith("Warning: ")
    assert text in result.stdout


def test_own_repository_on_pinned_release(own):
    result = check(own[0])
    assert (result.returncode, result.stdout) == (0, "")


def test_own_repository_off_pinned_tag(own):
    path, _ = own
    (path / PIN).write_text("v2\n")
    assert_warns(check(path), f"{SUB} is not on v2 of {PIN}")


def test_own_repository_with_unknown_tag(own):
    path, _ = own
    (path / PIN).write_text("v9\n")
    assert_warns(check(path), "tag v9 of .claude/pipeline-release is not fetched")


def test_own_repository_without_worktree(own):
    path, _ = own
    git(path, "worktree", "remove", "--force", SUB)
    assert_warns(check(path), f"{SUB} is not on v1")


def test_no_pin_and_no_submodule(plugin):
    assert_warns(check(plugin[0]), "neither a submodule")


def test_project_on_recorded_commit(project):
    result = check(project[0])
    assert (result.returncode, result.stdout) == (0, "")


def test_project_with_uninitialized_submodule(project):
    path, _ = project
    git(path, "submodule", "deinit", "-f", SUB)
    assert_warns(check(path), "is not initialized")


def test_project_with_submodule_off_recorded_commit(project):
    path, _ = project
    git(path / SUB, "checkout", "-q", "--detach", "v2")
    assert_warns(check(path), "is not on its recorded commit")


def test_hook_is_silent_on_pinned_release(own):
    result = run_hook(own[0])
    assert (result.returncode, result.stdout) == (0, "")


def test_hook_shows_warning_of_stale_release(own):
    path, _ = own
    (path / PIN).write_text("v2\n")

    result = run_hook(path)

    output = json.loads(result.stdout)
    assert "is not on v2" in output["systemMessage"]
    assert output["hookSpecificOutput"] == {
        "hookEventName": "SessionStart",
        "additionalContext": output["systemMessage"],
    }


def test_hook_warns_without_release(project):
    path, _ = project
    git(path, "submodule", "deinit", "-f", SUB)

    result = run_hook(path)

    message = json.loads(result.stdout)["systemMessage"]
    assert "check-release.sh is missing" in message
    assert "loads no pipeline rules, skills or hook" in message
