import json
import subprocess

import pytest
from conftest import SCRIPTS, load_script

SCRIPT = SCRIPTS / "deny-master-push.py"


@pytest.fixture(scope="module")
def hook():
    return load_script(SCRIPT.name)


def repo_on(path, branch):
    subprocess.run(["git", "init", "-q", "-b", branch, str(path)], check=True)
    return str(path)


@pytest.fixture
def issue_repo(tmp_path):
    return repo_on(tmp_path / "issue", "issue-64-x")


@pytest.fixture
def master_repo(tmp_path):
    return repo_on(tmp_path / "master", "master")


@pytest.mark.parametrize(
    "command",
    [
        "git push origin master",
        "git -C /abs/path push origin master",
        "git -c push.default=current push origin master",
        "git --git-dir=/x/.git push origin HEAD:master",
        "git --git-dir /x/.git --no-pager push origin master",
        "git -C /p push origin +HEAD:refs/heads/master",
        "cd /p && git -C /p push -u origin master",
        "git status; git push -o ci.skip origin master",
        "FOO=1 /usr/bin/git push origin master",
        "git push --mirror origin",
        "git push origin HEAD",
        "git push origin @",
        "git push origin +@",
        "git push 'unclosed",
        "git push origin :",
        "git push origin +:",
        "git push origin :master",
        "git push origin 'refs/heads/*:refs/heads/*'",
        "git push origin 'refs/heads/*'",
        "env git push origin master",
        "sudo FOO=1 nohup git push origin master",
        "command git -C /p push origin master",
    ],
)
def test_push_to_master_is_blocked(hook, master_repo, command):
    assert hook.is_blocked(command, master_repo)


@pytest.mark.parametrize(
    "command",
    [
        "git -C /p push -u origin issue-64-x",
        "git push origin HEAD",
        "git push origin @",
        "git push",
        "git log master",
        "git -C /p status",
        "git commit -m 'push to master'",
        "git push -o master origin issue-64-x",
        "git push origin :issue-64-old",
        "git push origin master:issue-64-x",
        "env git push origin issue-64-x",
    ],
)
def test_other_commands_are_allowed(hook, issue_repo, command):
    assert not hook.is_blocked(command, issue_repo)


def test_at_source_to_other_branch_on_master_is_allowed(hook, master_repo):
    assert not hook.is_blocked("git push origin @:refs/heads/issue-64-x", master_repo)


def test_bare_push_on_master_is_blocked(hook, master_repo, issue_repo):
    assert hook.is_blocked("git push", master_repo)
    assert hook.is_blocked(f"git -C {master_repo} push", issue_repo)
    assert hook.is_blocked(f"cd {master_repo} && git push", issue_repo)


@pytest.mark.parametrize(
    ("command", "exit_code"),
    [("git -C /p push origin master", 2), ("git push origin issue-64-x", 0)],
)
def test_hook_exit_code(issue_repo, command, exit_code):
    hook_input = {"cwd": issue_repo, "tool_input": {"command": command}}
    result = subprocess.run(
        [str(SCRIPT)],
        check=False,
        input=json.dumps(hook_input),
        capture_output=True,
        text=True,
    )
    assert result.returncode == exit_code
