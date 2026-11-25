import os
import subprocess

import pytest
from conftest import PIPELINE_URL, commit, git, script_path, write_executable

SCRIPT = script_path("bump.sh")
SUB = ".claude/skills/pipeline"


@pytest.fixture
def app(tmp_path, monkeypatch, pipeline_releases, default_branch):
    """A clone of a project with the pipeline at v1, and a gh stub on PATH."""
    remote, upstream, clone = (tmp_path / n for n in ("app.git", "upstream", "app"))
    git(tmp_path, "init", "-q", "--bare", "-b", default_branch, str(remote))
    git(tmp_path, "clone", "-q", str(remote), str(upstream))
    git(upstream, "submodule", "add", "-q", PIPELINE_URL, SUB)
    git(upstream / SUB, "checkout", "-q", "--detach", "v1")
    git(upstream, "add", SUB)
    commit(upstream, "README", "app")
    git(upstream, "push", "-q", "origin", default_branch)
    git(tmp_path, "clone", "-q", "--recurse-submodules", str(remote), str(clone))
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    write_executable(
        stubs / "gh",
        f"""printf '%s\\n' "$@" > {tmp_path}/gh_$1_$2
[ "$1 $2" != "release view" ] || [ -f {tmp_path}/no_release ] || echo "- Notes of $3"
[ ! -f {tmp_path}/no_release ]""",
    )
    monkeypatch.setenv("PATH", f"{stubs}:{os.environ['PATH']}")
    return clone


def gh_args(app, command):
    path = app.parent / f"gh_{command.replace(' ', '_')}"
    return path.read_text().splitlines() if path.exists() else None


def bump(cwd, *args):
    return subprocess.run(
        [str(SCRIPT), *args], cwd=cwd, check=False, capture_output=True, text=True
    )


def test_opens_pull_request_that_moves_submodule(
    app, pipeline_releases, default_branch
):
    result = bump(app, "v2")

    assert result.returncode == 0, result.stderr
    git(app, "fetch", "-q", "origin")
    pushed = git(app, "rev-parse", f"origin/bump-pipeline-v2:{SUB}")
    assert pushed == pipeline_releases["v2"]
    assert git(app, "log", "-1", "--format=%s", "origin/bump-pipeline-v2") == (
        "Bump pipeline to v2"
    )
    assert git(app, "rev-parse", "origin/bump-pipeline-v2~1") == git(
        app, "rev-parse", f"origin/{default_branch}"
    )
    args = gh_args(app, "pr create")
    assert args[args.index("--base") + 1] == default_branch
    assert args[args.index("--head") + 1] == "bump-pipeline-v2"
    assert "--label" not in args
    assert args[args.index("--title") + 1] == "Bump pipeline to v2"
    body = "\n".join(args[args.index("--body") + 1 :])
    assert f"`{SUB}` from v1 to v2" in body
    assert "- Notes of v2" in body
    assert gh_args(app, "release view")[3:5] == ["--repo", "fellek/agent-pipeline"]


def test_returns_to_previous_branch_with_clean_tree(
    app, pipeline_releases, default_branch
):
    bump(app, "v2")

    assert git(app, "branch", "--show-current") == default_branch
    assert git(app, "status", "--porcelain") == ""
    assert git(app / SUB, "rev-parse", "HEAD") == pipeline_releases["v1"]


def test_missing_release_creates_no_branch(app):
    (app.parent / "no_release").touch()

    result = bump(app, "v2")

    assert result.returncode == 1
    assert "release notes of v2" in result.stderr
    assert git(app, "branch", "--list", "bump-pipeline-v2") == ""


def test_unknown_tag_creates_no_branch(app):
    result = bump(app, "v9")

    assert result.returncode == 1
    assert "fetching tag v9 of the pipeline failed" in result.stderr
    assert git(app, "branch", "--list", "bump-pipeline-v9") == ""
    assert gh_args(app, "pr create") is None


def test_refuses_tag_already_on_default_branch(app):
    result = bump(app, "v1")

    assert result.returncode == 1
    assert "at v1" in result.stderr
    assert gh_args(app, "pr create") is None


def test_refuses_working_tree_with_changes(app):
    (app / "README").write_text("changed")

    result = bump(app, "v2")

    assert result.returncode == 1
    assert "has changes" in result.stderr
    assert gh_args(app, "pr create") is None


def test_refuses_existing_branch(app):
    git(app, "branch", "bump-pipeline-v2")

    result = bump(app, "v2")

    assert result.returncode == 1
    assert "branch bump-pipeline-v2 exists" in result.stderr


def test_refuses_project_without_submodule(tmp_path, git_identity):
    app = tmp_path / "other"
    app.mkdir()
    git(app, "init", "-q")

    result = bump(app, "v2")

    assert result.returncode == 1
    assert "no submodule" in result.stderr


@pytest.mark.parametrize("args", [(), ("v1", "v2"), ("",)])
def test_rejects_bad_arguments(app, args):
    assert bump(app, *args).returncode == 1
