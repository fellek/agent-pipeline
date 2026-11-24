import json
import subprocess

import pytest
from conftest import git, load_script, script_path

SCRIPT = script_path("deny-default-branch-push.py")


@pytest.fixture(scope="module")
def hook():
    return load_script(SCRIPT.name)


def repo_on(path, branch, default):
    path.mkdir()
    git(path, "init", "-q", "-b", branch)
    git(
        path,
        "symbolic-ref",
        "refs/remotes/origin/HEAD",
        f"refs/remotes/origin/{default}",
    )
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
def test_push_with_unknown_default_branch_is_blocked(hook, tmp_path, cwd):
    if cwd is None:
        git(tmp_path, "init", "-q")
        cwd = str(tmp_path)
    assert hook.is_blocked("git push origin issue-64-x", cwd)
    assert not hook.is_blocked("git status", cwd)


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
