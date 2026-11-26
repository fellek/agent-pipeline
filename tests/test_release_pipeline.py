import json
import os
import pwd
import subprocess

import pytest
from conftest import PIPELINE_URL, commit, git, script_path, write_executable

PIN = ".claude/pipeline-release"
MANIFEST = ".claude-plugin/plugin.json"


@pytest.fixture
def gh(tmp_path, monkeypatch):
    """A gh stub: the newest release is v0.3.4, `pr list` prints the file `open`."""
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    write_executable(
        stubs / "gh",
        f"""printf '%s\\n' "$@" > {tmp_path}/gh_$1_$2
case "$1 $2" in
  "release list") echo v0.3.4 ;;
  "pr list") cat {tmp_path}/open 2>/dev/null || true ;;
  "pr create") echo https://github.com/fellek/agent-pipeline/pull/12 ;;
esac""",
    )
    monkeypatch.setenv("PATH", f"{stubs}:{os.environ['PATH']}")
    return tmp_path


@pytest.fixture
def own(tmp_path, pipeline_releases, gh):
    """A clone of the pipeline repository at version 0.3.4."""
    upstream, clone = tmp_path / "own-upstream", tmp_path / "own"
    git(tmp_path, "clone", "-q", PIPELINE_URL, str(upstream))
    set_version(upstream, "0.3.4")
    git(upstream, "push", "-q", "origin", "HEAD")
    git(tmp_path, "clone", "-q", PIPELINE_URL, str(clone))
    return upstream, clone


def set_version(repo, version):
    manifest = json.loads((repo / MANIFEST).read_text())
    commit(repo, MANIFEST, json.dumps({**manifest, "version": version}, indent=2))


def release(cwd, *args):
    return subprocess.run(
        [str(script_path("release-pipeline.sh")), *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def gh_args(tmp_path, command):
    path = tmp_path / f"gh_{command.replace(' ', '_')}"
    return path.read_text().splitlines() if path.exists() else None


def test_lists_the_version_of_each_level(own):
    result = release(own[1])
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (
        "Release nach v0.3.4: major v1.0.0, minor v0.4.0, patch v0.3.5"
    )


def test_level_opens_the_bump_pull_request(own, gh):
    _, clone = own
    before = git(clone, "rev-parse", "--abbrev-ref", "HEAD")

    result = release(clone, "minor")

    assert result.returncode == 0, result.stderr
    args = gh_args(gh, "pr create")
    assert args[args.index("--title") + 1] == "Bump plugin to 0.4.0"
    git(clone, "fetch", "-q", "origin")
    pushed = json.loads(git(clone, "show", f"origin/bump-plugin-0.4.0:{MANIFEST}"))
    assert pushed["version"] == "0.4.0"
    sha = git(clone, "rev-parse", "origin/bump-plugin-0.4.0")
    user = pwd.getpwuid(os.getuid()).pw_name
    lines = result.stdout.splitlines()
    assert lines[0] == "https://github.com/fellek/agent-pipeline/pull/12"
    assert f"gate review --manual {user} 12 {sha} approve" in lines[2]
    assert f"gate merge 12 {sha}" in lines[3]
    assert git(clone, "rev-parse", "--abbrev-ref", "HEAD") == before
    assert git(clone, "branch", "--list", "bump-plugin-*") == ""
    assert git(clone, "status", "--porcelain") == ""


def test_open_bump_pull_request_is_named_again(own, gh):
    (gh / "open").write_text(f"7 {'c' * 40} https://pr/7\n")

    result = release(own[1], "patch")

    assert result.returncode == 0, result.stderr
    assert gh_args(gh, "pr create") is None
    assert result.stdout.splitlines()[0] == "https://pr/7"
    assert f"gate merge 7 {'c' * 40}" in result.stdout


def test_after_the_merge_prints_the_root_command(own, gh):
    upstream, clone = own
    set_version(upstream, "0.3.5")
    git(upstream, "push", "-q", "origin", "HEAD")

    result = release(clone, "patch")

    assert result.returncode == 0, result.stderr
    sha = git(upstream, "rev-parse", "HEAD")
    assert result.stdout.splitlines()[-1].split()[-2:] == ["v0.3.5", sha]
    assert "sudo -u pipeline-gate /opt/pipeline/gate release " in result.stdout
    assert gh_args(gh, "pr create") is None


def test_refuses_a_version_of_another_level(own):
    upstream, clone = own
    set_version(upstream, "0.4.0")
    git(upstream, "push", "-q", "origin", "HEAD")

    result = release(clone, "patch")

    assert result.returncode == 1
    assert "has version 0.4.0, neither 0.3.4 nor 0.3.5" in result.stderr


def test_refuses_outside_the_pipeline_repository(own):
    _, clone = own
    git(clone, "rm", "-q", PIN)
    git(clone, "commit", "-qm", "no pin")

    result = release(clone)

    assert result.returncode == 1
    assert "run it in the pipeline repository" in result.stderr


def test_refuses_an_unknown_level(own):
    result = release(own[1], "huge")
    assert result.returncode == 1
    assert "usage" in result.stderr
