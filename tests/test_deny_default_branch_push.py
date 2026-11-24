import json
import subprocess

import pytest
from conftest import git, load_script, script_path

SCRIPT = script_path("deny-default-branch-push.py")


@pytest.fixture(scope="module")
def hook():
    return load_script(SCRIPT.name)


def set_remote_head(path, remote, default, *, exists=True):
    if exists:
        empty_tree = git(path, "hash-object", "-t", "tree", "/dev/null", "-w")
        commit = git(path, "commit-tree", "-m", "x", empty_tree)
        git(path, "update-ref", f"refs/remotes/{remote}/{default}", commit)
    git(
        path,
        "symbolic-ref",
        f"refs/remotes/{remote}/HEAD",
        f"refs/remotes/{remote}/{default}",
    )


def repo_on(path, branch, default):
    path.mkdir()
    git(path, "init", "-q", "-b", branch)
    set_remote_head(path, "origin", default)
    return str(path)


@pytest.fixture
def issue_repo(tmp_path, default_branch):
    return repo_on(tmp_path / "issue", "issue-64-x", default_branch)


@pytest.fixture
def default_repo(tmp_path, default_branch):
    return repo_on(tmp_path / "default", default_branch, default_branch)


@pytest.mark.parametrize(
    "command",
    [
        "git push origin {default}",
        "git -C {repo} push origin {default}",
        "git -c push.default=current push origin {default}",
        "git --git-dir=/x/.git push origin HEAD:{default}",
        "git --git-dir /x/.git --no-pager push origin {default}",
        "git -C {repo} push origin +HEAD:refs/heads/{default}",
        "cd {repo} && git -C {repo} push -u origin {default}",
        "git status; git push -o ci.skip origin {default}",
        "FOO=1 /usr/bin/git push origin {default}",
        "git push --mirror origin",
        "git push origin HEAD",
        "git push origin @",
        "git push origin +@",
        "git push 'unclosed",
        "git push origin :",
        "git push origin +:",
        "git push origin :{default}",
        "git push origin 'refs/heads/*:refs/heads/*'",
        "git push origin 'refs/heads/*'",
        "env git push origin {default}",
        "sudo FOO=1 nohup git push origin {default}",
        "command git -C {repo} push origin {default}",
    ],
)
def test_push_to_default_branch_is_blocked(hook, default_repo, default_branch, command):
    command = command.format(default=default_branch, repo=default_repo)
    assert hook.is_blocked(command, default_repo)


@pytest.mark.parametrize(
    "command",
    [
        "git -C {repo} push -u origin issue-64-x",
        "git push origin HEAD",
        "git push origin @",
        "git push",
        "git log {default}",
        "git -C /p status",
        "git commit -m 'push to {default}'",
        "git push -o {default} origin issue-64-x",
        "git push origin :issue-64-old",
        "git push origin {default}:issue-64-x",
        "git push origin {other}",
        "env git push origin issue-64-x",
    ],
)
def test_other_commands_are_allowed(
    hook, issue_repo, default_branch, other_branch, command
):
    command = command.format(
        default=default_branch, other=other_branch, repo=issue_repo
    )
    assert not hook.is_blocked(command, issue_repo)


def test_at_source_to_other_branch_on_default_is_allowed(hook, default_repo):
    assert not hook.is_blocked("git push origin @:refs/heads/issue-64-x", default_repo)


def test_bare_push_on_default_branch_is_blocked(hook, default_repo, issue_repo):
    assert hook.is_blocked("git push", default_repo)
    assert hook.is_blocked(f"git -C {default_repo} push", issue_repo)
    assert hook.is_blocked(f"cd {default_repo} && git push", issue_repo)


@pytest.mark.parametrize("cwd", ["/nonexistent", None])
def test_unknown_default_branch_protects_main_and_master(hook, tmp_path, cwd):
    if cwd is None:
        git(tmp_path, "init", "-q")
        git(tmp_path, "remote", "add", "origin", str(tmp_path / "missing"))
        cwd = str(tmp_path)
    assert hook.is_blocked("git push origin main", cwd)
    assert hook.is_blocked("git push origin HEAD:master", cwd)
    assert not hook.is_blocked("git push origin issue-64-x", cwd)
    assert not hook.is_blocked("git status", cwd)


def test_unknown_default_branch_is_not_fetched(hook, tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "remote", "add", "origin", str(tmp_path / "missing"))
    hook.is_blocked("git push origin main", str(tmp_path))
    with pytest.raises(subprocess.CalledProcessError):
        git(tmp_path, "symbolic-ref", "refs/remotes/origin/HEAD")


def test_stale_origin_head_protects_old_and_common_names(hook, tmp_path):
    # origin/HEAD still points to the old default branch after a rename and prune.
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "issue-64-x")
    set_remote_head(repo, "origin", "trunk", exists=False)
    for branch in ("trunk", "main", "master"):
        assert hook.is_blocked(f"git push origin {branch}", str(repo))
    assert not hook.is_blocked("git push origin issue-64-x", str(repo))


def test_reads_default_branch_of_pushed_remote(hook, issue_repo, default_branch):
    upstream_default = "develop"
    set_remote_head(issue_repo, "upstream", upstream_default)
    assert hook.is_blocked(f"git push upstream {upstream_default}", issue_repo)
    assert not hook.is_blocked(f"git push upstream {default_branch}", issue_repo)
    assert hook.is_blocked(f"git push origin {default_branch}", issue_repo)


def test_remote_without_head_protects_main_and_master(hook, issue_repo):
    assert hook.is_blocked("git push github main", issue_repo)
    assert hook.is_blocked("git push github master", issue_repo)
    assert not hook.is_blocked("git push github issue-64-x", issue_repo)


@pytest.mark.parametrize(
    ("command", "exit_code"),
    [("git -C {repo} push origin {default}", 2), ("git push origin issue-64-x", 0)],
)
def test_hook_exit_code(issue_repo, default_branch, command, exit_code):
    command = command.format(default=default_branch, repo=issue_repo)
    hook_input = {"cwd": issue_repo, "tool_input": {"command": command}}
    result = subprocess.run(
        [str(SCRIPT)],
        check=False,
        input=json.dumps(hook_input),
        capture_output=True,
        text=True,
    )
    assert result.returncode == exit_code
