import os
import subprocess

import pytest
from conftest import PIPELINE_URL, commit, git, script_path, write_executable

SUB = ".claude/skills/pipeline"
PIN = ".claude/pipeline-release"


@pytest.fixture
def gh(tmp_path, monkeypatch):
    """A gh stub: `release list` prints the newest tag from the file `newest`."""
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    (tmp_path / "newest").write_text("v2")
    write_executable(
        stubs / "gh",
        f"""printf '%s\\n' "$@" > {tmp_path}/gh_$1_$2
case "$1 $2" in
  "release list") cat {tmp_path}/newest ;;
  "release view") echo "- Notes of $3" ;;
esac""",
    )
    monkeypatch.setenv("PATH", f"{stubs}:{os.environ['PATH']}")
    return tmp_path


def gh_args(tmp_path, command):
    path = tmp_path / f"gh_{command.replace(' ', '_')}"
    return path.read_text().splitlines() if path.exists() else None


@pytest.fixture
def project(tmp_path, pipeline_releases, gh):
    """A clone of a project with the pipeline submodule at v1."""
    remote, upstream, clone = (tmp_path / n for n in ("app.git", "upstream", "app"))
    git(tmp_path, "init", "-q", "--bare", str(remote))
    git(tmp_path, "clone", "-q", str(remote), str(upstream))
    git(upstream, "submodule", "add", "-q", PIPELINE_URL, SUB)
    git(upstream / SUB, "checkout", "-q", "--detach", "v1")
    git(upstream, "add", SUB)
    commit(upstream, "README", "app")
    git(upstream, "push", "-q", "origin", "HEAD")
    git(tmp_path, "clone", "-q", "--recurse-submodules", str(remote), str(clone))
    git(clone, "config", "submodule.recurse", "true")
    return upstream, clone


@pytest.fixture
def own(tmp_path, pipeline_releases, gh):
    """A clone of the pipeline repository pinned to v1, with its release worktree."""
    upstream, clone = tmp_path / "own-upstream", tmp_path / "own"
    git(tmp_path, "clone", "-q", PIPELINE_URL, str(upstream))
    commit(upstream, PIN, "v1\n")
    git(upstream, "push", "-q", "origin", "HEAD")
    git(tmp_path, "clone", "-q", PIPELINE_URL, str(clone))
    git(clone, "worktree", "add", "-q", "--detach", SUB, "v1")
    return upstream, clone


def run(cwd, script, *args):
    return subprocess.run(
        [str(script), *args], cwd=cwd, check=False, capture_output=True, text=True
    )


def update(cwd):
    return run(cwd, script_path("update-pipeline.sh"))


def release_changed(cwd, *args):
    # The copy in the release, as the autopilot runs it: it records its own commit.
    return run(cwd, cwd / SUB / "bin" / "release-changed.sh", *args)


def move_pin_on_origin(upstream, tag, *, own):
    git(upstream, "pull", "-q")
    if own:
        commit(upstream, PIN, f"{tag}\n")
    else:
        git(upstream / SUB, "checkout", "-q", "--detach", tag)
        git(upstream, "add", SUB)
        git(upstream, "commit", "-qm", f"Bump pipeline to {tag}")
    git(upstream, "push", "-q", "origin", "HEAD")


@pytest.mark.parametrize("fixture", ["project", "own"])
def test_opens_bump_pull_request_to_newest_release(request, fixture, gh):
    _, clone = request.getfixturevalue(fixture)

    result = update(clone)

    assert result.returncode == 0, result.stderr
    args = gh_args(gh, "pr create")
    assert args[args.index("--title") + 1] == "Bump pipeline to v2"
    assert gh_args(gh, "release list")[:4] == [
        "release",
        "list",
        "--repo",
        "fellek/agent-pipeline",
    ]


def test_bump_in_own_repository_moves_pin(own, gh):
    _, clone = own

    assert update(clone).returncode == 0

    git(clone, "fetch", "-q", "origin")
    assert git(clone, "show", f"origin/bump-pipeline-v2:{PIN}") == "v2"
    body = "\n".join(gh_args(gh, "pr create"))
    assert f"`{PIN}` from v1 to v2" in body
    assert "- Notes of v2" in body
    assert git(clone / SUB, "rev-parse", "HEAD") == git(clone, "rev-parse", "v1")
    assert git(clone, "status", "--porcelain") == ""


@pytest.mark.parametrize("fixture", ["project", "own"])
def test_changes_nothing_on_newest_release(request, fixture, gh):
    _, clone = request.getfixturevalue(fixture)
    (gh / "newest").write_text("v1")

    result = update(clone)

    assert result.returncode == 0, result.stderr
    assert "up to date" in result.stdout
    assert gh_args(gh, "pr create") is None
    assert git(clone, "branch", "--list", "bump-pipeline-*") == ""


def test_fails_without_release(project, gh):
    (gh / "newest").write_text("")

    result = update(project[1])

    assert result.returncode == 1
    assert "has no release" in result.stderr
    assert gh_args(gh, "pr create") is None


@pytest.mark.parametrize("own_repo", [False, True])
def test_release_changed_after_merged_pin(request, own_repo):
    upstream, clone = request.getfixturevalue("own" if own_repo else "project")
    assert release_changed(clone, "record").returncode == 0

    unchanged = release_changed(clone)
    move_pin_on_origin(upstream, "v2", own=own_repo)
    if not own_repo:
        # git pull moves the submodule, the running session stays on v1.
        git(clone, "pull", "-q")
    changed = release_changed(clone)

    assert (unchanged.returncode, unchanged.stdout) == (0, "")
    assert (changed.returncode, changed.stdout.strip()) == (0, "v2"), changed.stderr


def test_release_changed_needs_record(project):
    result = release_changed(project[1])
    assert result.returncode == 1
    assert "record" in result.stderr


def test_update_skips_pre_releases_unless_asked(project, gh):
    _, clone = project

    update(clone)
    stable = gh_args(gh, "release list")
    (gh / "gh_release_list").unlink()
    git(clone, "branch", "-q", "-D", "bump-pipeline-v2")
    run(clone, script_path("update-pipeline.sh"), "--pre")

    assert "--exclude-pre-releases" in stable
    assert "--exclude-pre-releases" not in gh_args(gh, "release list")


def rollback(cwd):
    return run(cwd, script_path("rollback-pipeline.sh"))


@pytest.mark.parametrize("own_repo", [False, True])
def test_rollback_opens_the_pull_request_to_the_previous_release(request, own_repo):
    upstream, clone = request.getfixturevalue("own" if own_repo else "project")
    gh = request.getfixturevalue("gh")
    move_pin_on_origin(upstream, "v2", own=own_repo)
    git(clone, "pull", "-q")

    result = rollback(clone)

    assert result.returncode == 0, result.stderr
    args = gh_args(gh, "pr create")
    assert args[args.index("--title") + 1] == "Bump pipeline to v1"


def test_rollback_fails_without_an_earlier_release(project, gh):
    _, clone = project

    result = rollback(clone)

    assert result.returncode == 1
    assert "no release before the current one" in result.stderr
    assert gh_args(gh, "pr create") is None
