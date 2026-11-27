import json
import subprocess

import pytest
from conftest import load_script, script_path

SCRIPT = script_path("deny-sandboxed-github-call.py")


@pytest.fixture(scope="module")
def hook():
    return load_script(SCRIPT.name)


@pytest.mark.parametrize(
    "command",
    [
        "cd /repo && git push -u origin issue-1-x",
        "git push -u origin issue-1-x 2>&1",
        "git push origin issue-1-x | tail -5",
        "git add . && git commit -m x && git push origin issue-1-x",
        "git status; git fetch origin",
        "git status\ngit pull",
        "git -C /repo push origin issue-1-x",
        "git -c push.default=current push",
        "FOO=1 git push origin issue-1-x",
        "env git push origin issue-1-x",
        "timeout 60 git push origin issue-1-x",
        "/usr/bin/git push origin issue-1-x",
        'gh pr create --head issue-1-x --body "$(cat .pipeline/body.md)"',
        "gh issue comment 1 --body-file - <<'EOF'\nx\nEOF",
        "gh pr view 1 > .pipeline/pr.json",
        "gate review 1 abc 2>&1",
        "echo x | gh issue comment 1 --body-file -",
    ],
)
def test_github_call_in_sandbox_is_blocked(hook, command):
    assert hook.is_blocked(command)


@pytest.mark.parametrize(
    "command",
    [
        "git push -u origin issue-1-x",
        "git fetch origin",
        "git pull",
        "gh pr create --head issue-1-x --body-file .pipeline/body.md",
        "gh issue comment 1 --body ''",
        "gh pr create --title 'a > b; c' --head issue-1-x --body-file .pipeline/b.md",
        "gate review 1 abc",
        "git add . && git commit -m 'push the fix'",
        "cd /repo && git status 2>&1",
        "uv run pytest | tail -5",
        "git log --oneline | grep push",
        "git push 'unclosed",
    ],
)
def test_other_calls_pass(hook, command):
    assert not hook.is_blocked(command)


def run_hook(command):
    return subprocess.run(
        [SCRIPT],
        input=json.dumps({"tool_input": {"command": command}}),
        capture_output=True,
        text=True,
        check=False,
    )


def test_blocked_call_exits_2_with_the_plain_form():
    result = run_hook("cd /repo && git push -u origin issue-1-x")
    assert result.returncode == 2
    assert "git push -u origin <branch>" in result.stderr


def test_plain_call_exits_0():
    result = run_hook("git push -u origin issue-1-x")
    assert result.returncode == 0
    assert result.stderr == ""
