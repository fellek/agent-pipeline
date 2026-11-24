import shutil
import subprocess

import pytest
from conftest import commit, git, script_path

SCRIPT = "require-project-root.sh"


def run(script, cwd):
    return subprocess.run(
        [str(script)], cwd=cwd, check=False, capture_output=True, text=True
    )


@pytest.fixture
def plugin(tmp_path, git_identity):
    """A repository of the plugin with the script at host/."""
    path = tmp_path / "plugin"
    path.mkdir()
    git(path, "init", "-q")
    (path / "host").mkdir()
    shutil.copy(script_path(SCRIPT), path / "host")
    git(path, "add", ".")
    git(path, "commit", "-qm", "plugin")
    return path


@pytest.fixture
def app(tmp_path, git_identity):
    path = tmp_path / "app"
    path.mkdir()
    git(path, "init", "-q")
    commit(path, "README", "app")
    return path


def test_accepts_project_root(plugin, app):
    result = run(plugin / "host" / SCRIPT, app)
    assert (result.returncode, result.stdout) == (0, "")


def test_rejects_subdirectory(plugin, app):
    (app / "docs").mkdir()
    result = run(plugin / "host" / SCRIPT, app / "docs")
    assert result.returncode == 1
    assert result.stdout == "run it in the project root\n"


def test_rejects_directory_outside_git(plugin, tmp_path):
    (tmp_path / "plain").mkdir()
    result = run(plugin / "host" / SCRIPT, tmp_path / "plain")
    assert result.returncode == 1
    assert result.stdout == "run it in the project root\n"


def test_rejects_plugin_submodule(plugin, app):
    git(
        app,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        str(plugin),
        ".claude/skills/pipeline",
    )
    submodule = app / ".claude" / "skills" / "pipeline"
    assert run(submodule / "host" / SCRIPT, app).returncode == 0
    result = run(submodule / "host" / SCRIPT, submodule)
    assert result.returncode == 1
    assert result.stdout == "run it in the project root, not in the plugin\n"


def test_rejects_release_worktree_of_plugin(plugin):
    # use-release.sh: the plugin repository runs a release from a linked worktree.
    worktree = plugin / ".claude" / "skills" / "pipeline"
    git(plugin, "worktree", "add", "-q", "--detach", str(worktree))
    assert run(worktree / "host" / SCRIPT, plugin).returncode == 0
    result = run(worktree / "host" / SCRIPT, worktree)
    assert result.returncode == 1
    assert result.stdout == "run it in the project root, not in the plugin\n"


def test_accepts_clone_of_plugin_as_own_project(plugin):
    assert run(plugin / "host" / SCRIPT, plugin).returncode == 0


def test_check_fork_rejects_subdirectory(tmp_path, app):
    host = tmp_path / "fork" / "host"
    host.mkdir(parents=True)
    for name in ("check-fork.sh", SCRIPT):
        shutil.copy(script_path(name), host)
    (app / "docs").mkdir()
    result = run(host / "check-fork.sh", app / "docs")
    assert result.returncode == 1
    assert "project root" in result.stdout
    assert not (app / "docs" / ".pipeline").exists()
