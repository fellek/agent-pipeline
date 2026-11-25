import shutil
import subprocess

import pytest
from conftest import commit, git, script_path

SCRIPT = script_path("use-release.sh")
WORKTREE = ".claude/skills/pipeline"
PIN = ".claude/pipeline-release"


@pytest.fixture
def releases(repos, default_branch):
    upstream, clone = repos
    tags = {}
    for tag in ("v1", "v2"):
        tags[tag] = commit(upstream, tag, tag)
        git(upstream, "tag", tag)
    git(upstream, "push", "origin", default_branch, "v1", "v2")
    return clone, tags


def use_release(cwd, tag=None, *args):
    if tag is not None:
        (cwd / ".claude").mkdir(exist_ok=True)
        (cwd / PIN).write_text(f"{tag}\n")
    return subprocess.run(
        [str(SCRIPT), *args], cwd=cwd, check=False, capture_output=True, text=True
    )


def test_checks_out_release_as_worktree(releases):
    clone, tags = releases

    result = use_release(clone, "v1")

    assert result.returncode == 0, result.stderr
    worktree = clone / WORKTREE
    assert git(worktree, "rev-parse", "HEAD") == tags["v1"]
    assert git(worktree, "branch", "--show-current") == ""
    assert str(worktree) in git(clone, "worktree", "list")
    assert git(clone, "branch", "--show-current") == "feature"


def test_switches_existing_worktree_to_other_release(releases):
    clone, tags = releases
    use_release(clone, "v1")

    result = use_release(clone, "v2")

    assert result.returncode == 0, result.stderr
    assert git(clone / WORKTREE, "rev-parse", "HEAD") == tags["v2"]


def test_keeps_worktree_with_changes(releases):
    clone, tags = releases
    use_release(clone, "v1")
    (clone / WORKTREE / "v1").write_text("changed")

    result = use_release(clone, "v2")

    assert result.returncode == 1
    assert "has changes" in result.stderr
    assert git(clone / WORKTREE, "rev-parse", "HEAD") == tags["v1"]


def test_unknown_tag_creates_no_worktree(releases):
    clone, _ = releases

    result = use_release(clone, "v9")

    assert result.returncode == 1
    assert "fetching tag v9 from origin failed" in result.stderr
    assert "refs/tags/v9" in result.stderr
    assert not (clone / WORKTREE).exists()


def test_unreachable_origin_shows_git_error(releases, tmp_path):
    clone, _ = releases
    git(clone, "remote", "set-url", "origin", str(tmp_path / "missing"))

    result = use_release(clone, "v1")

    assert result.returncode == 1
    assert "does not appear to be a git repository" in result.stderr
    assert "fetching tag v1 from origin failed" in result.stderr
    assert not (clone / WORKTREE).exists()


def test_refuses_directory_that_is_no_worktree(releases):
    clone, _ = releases
    (clone / WORKTREE).mkdir(parents=True)

    result = use_release(clone, "v1")

    assert result.returncode == 1
    assert "not a worktree" in result.stderr
    assert git(clone, "branch", "--show-current") == "feature"


def test_refuses_independent_clone(releases):
    clone, tags = releases
    git(clone, "clone", "-q", str(clone), WORKTREE)

    result = use_release(clone, "v1")

    assert result.returncode == 1
    assert "not a worktree of this repository" in result.stderr
    assert git(clone / WORKTREE, "rev-parse", "HEAD") != tags["v1"]


def test_adds_worktree_again_after_its_directory_was_deleted(releases):
    clone, tags = releases
    use_release(clone, "v1")
    shutil.rmtree(clone / WORKTREE)

    result = use_release(clone, "v2")

    assert result.returncode == 0, result.stderr
    assert git(clone / WORKTREE, "rev-parse", "HEAD") == tags["v2"]


def test_runs_only_in_repository_root(releases):
    clone, _ = releases
    (clone / "sub").mkdir()

    (clone / ".claude").mkdir(exist_ok=True)
    (clone / PIN).write_text("v1\n")

    result = use_release(clone / "sub")

    assert result.returncode == 1
    assert not (clone / "sub" / WORKTREE).exists()


def test_rejects_arguments(releases):
    clone, _ = releases
    assert use_release(clone, "v1", "v2").returncode == 1
    assert not (clone / WORKTREE).exists()


@pytest.mark.parametrize("pin", [None, ""])
def test_fails_without_pinned_tag(releases, pin):
    clone, _ = releases

    result = use_release(clone, pin)

    assert result.returncode == 1
    assert ("empty" if pin == "" else "missing") in result.stderr
    assert not (clone / WORKTREE).exists()
