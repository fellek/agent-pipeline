import io
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
def issue_repo(tmp_path, git_identity, default_branch):
    return repo_on(tmp_path / "issue", "issue-64-x", default_branch)


@pytest.fixture
def default_repo(tmp_path, git_identity, default_branch):
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
    "command",
    [
        "cd ~/issue && git push origin",
        "cd ~/issue && git push origin HEAD",
        "cd $PROJECT && git push -u origin",
        "cd ${PROJECT} && git push",
        "git -C ~/issue push origin",
        "git -C $PROJECT push origin @",
    ],
)
def test_cd_and_dash_c_expand_home_and_variables(
    hook, tmp_path, monkeypatch, git_identity, default_branch, command
):
    monkeypatch.setenv("HOME", str(tmp_path))
    for name, branch, reason in [
        ("issue", "issue-64-x", None),
        ("default", default_branch, hook.DEFAULT_BRANCH),
    ]:
        repo = repo_on(tmp_path / name, branch, default_branch)
        monkeypatch.setenv("PROJECT", repo)
        assert hook.is_blocked(command.replace("issue", name), "/") == reason


@pytest.mark.parametrize(
    "command",
    [
        "git push",
        "git push origin",
        "git push origin HEAD",
        "git push origin @",
        "cd $UNSET_IN_HOOK && git push origin",
    ],
)
def test_unknown_current_branch_is_blocked_with_own_message(
    hook, issue_repo, monkeypatch, command
):
    # A detached HEAD, and a cd the hook cannot follow: the shell might be on the
    # default branch, so the push is blocked, but not as a push to the default branch.
    monkeypatch.delenv("UNSET_IN_HOOK", raising=False)
    git(issue_repo, "switch", "-q", "--detach", "refs/remotes/origin/HEAD")
    for cwd in (issue_repo, "/nonexistent"):
        reason = hook.is_blocked(command, cwd)
        assert reason and reason.startswith("Cannot tell which branch")
    assert not hook.is_blocked("git push origin HEAD:issue-64-x", issue_repo)
    assert hook.is_blocked("git push origin :", issue_repo) == hook.DEFAULT_BRANCH


@pytest.mark.parametrize(
    "command", ["git push --repo=upstream", "git push --repo upstream"]
)
def test_repo_option_selects_the_remote(hook, tmp_path, git_identity, command):
    repo = repo_on(tmp_path / "repo", "develop", "main")
    set_remote_head(repo, "upstream", "develop")
    assert hook.is_blocked(command, repo) == hook.DEFAULT_BRANCH
    # As in git, the repository argument takes precedence over --repo.
    assert hook.is_blocked(f"{command} origin", repo) is None
    assert hook.is_blocked(f"{command} upstream develop", repo) == hook.DEFAULT_BRANCH


ORIGIN_URL = "https://github.com/o/app.git"


@pytest.fixture
def remote_repo(tmp_path, git_identity):
    """A clone on issue-64-x whose origin has a URL and the default branch develop."""
    repo = tmp_path / "app"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "issue-64-x")
    git(repo, "remote", "add", "origin", ORIGIN_URL)
    set_remote_head(repo, "origin", "develop")
    return str(repo)


@pytest.mark.parametrize(
    "url", [ORIGIN_URL, "https://github.com/o/app", "https://github.com/o/app/"]
)
def test_push_to_url_of_remote_reads_its_default_branch(hook, remote_repo, url):
    assert hook.is_blocked(f"git push {url} develop", remote_repo)
    assert not hook.is_blocked(f"git push {url} issue-64-x", remote_repo)


def test_push_to_push_url_of_remote_reads_its_default_branch(hook, remote_repo):
    git(remote_repo, "remote", "set-url", "--push", "origin", "git@github.com:o/app")
    assert hook.is_blocked("git push git@github.com:o/app.git develop", remote_repo)


def test_push_to_unknown_url_protects_all_default_branches(hook, remote_repo):
    git(remote_repo, "switch", "-q", "-c", "develop")
    for command in [
        "git push git@github.com:o/app.git develop",
        "git push git@github.com:o/app.git HEAD",
        "git push git@github.com:o/app.git",
        "git push ../other main",
        "git push ../other master",
    ]:
        assert hook.is_blocked(command, remote_repo), command
    assert not hook.is_blocked("git push ../other issue-64-x", remote_repo)


@pytest.mark.parametrize(
    "key", ["remote.pushDefault", "branch.develop.pushRemote", "branch.develop.remote"]
)
def test_bare_push_reads_push_remote_from_config(hook, remote_repo, key):
    set_remote_head(remote_repo, "upstream", "develop")
    git(remote_repo, "remote", "add", "upstream", "https://github.com/u/app.git")
    git(
        remote_repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/x"
    )
    git(remote_repo, "switch", "-q", "-c", "develop")
    assert not hook.is_blocked("git push", remote_repo)
    git(remote_repo, "config", key, "upstream")
    assert hook.is_blocked("git push", remote_repo)


@pytest.mark.parametrize("mode", ["upstream", "tracking"])
def test_push_without_refspec_to_upstream_branch_is_blocked(hook, remote_repo, mode):
    # git switch -c issue-64-y origin/develop sets this upstream.
    git(remote_repo, "config", "branch.issue-64-x.remote", "origin")
    git(remote_repo, "config", "branch.issue-64-x.merge", "refs/heads/develop")
    assert not hook.is_blocked("git push", remote_repo)
    git(remote_repo, "config", "push.default", mode)
    assert hook.is_blocked("git push", remote_repo)
    assert hook.is_blocked("git push origin", remote_repo)
    assert hook.is_blocked(f"git push {ORIGIN_URL}", remote_repo)
    assert not hook.is_blocked("git push origin issue-64-x", remote_repo)


def test_push_without_refspec_with_matching_is_blocked(hook, remote_repo):
    git(remote_repo, "config", "push.default", "matching")
    assert hook.is_blocked("git push", remote_repo)
    assert hook.is_blocked("git push origin", remote_repo)


@pytest.mark.parametrize(
    ("refspec", "blocked"),
    [("HEAD:refs/heads/develop", True), ("refs/heads/*", True), ("HEAD", False)],
)
def test_push_without_refspec_follows_remote_push_config(
    hook, remote_repo, refspec, blocked
):
    git(remote_repo, "config", "remote.origin.push", refspec)
    assert bool(hook.is_blocked("git push", remote_repo)) is blocked
    assert bool(hook.is_blocked("git push origin", remote_repo)) is blocked
    assert not hook.is_blocked("git push origin issue-64-x", remote_repo)


@pytest.mark.parametrize(
    ("command", "exit_code", "message"),
    [
        ("git -C {repo} push origin {default}", 2, "Pushing to the default branch"),
        ("cd /nonexistent && git push origin", 2, "Cannot tell which branch"),
        ("git push origin issue-64-x", 0, ""),
    ],
)
def test_hook_exit_code(issue_repo, default_branch, command, exit_code, message):
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
    assert result.stderr.startswith(message)


@pytest.mark.parametrize(
    "command",
    [
        "{{ git push origin {default}; }}",
        "if true; then git push origin {default}; fi",
        "if git push origin {default}; then :; fi",
        "while true; do git push origin {default}; done",
        "! git push origin {default}",
        "echo `git push origin {default}`",
        'echo "$(git push origin {default})"',
        'x="`git push origin {default}`"',
        "bash -c 'git push origin {default}'",
        "/bin/sh -e -c 'cd {default_repo} && git push'",
        "eval git push origin {default}",
        "exec git push origin {default}",
        "env -u FOO git push origin {default}",
        "sudo -u root git push origin {default}",
        "time -p git push origin {default}",
        "env -i -u FOO HOME=/x git push origin {default}",
        "env -C {default_repo} git push",
        "env --chdir={default_repo} git push",
        "env --chdir {default_repo} git push",
        "sudo -D {default_repo} git push",
        "sudo --chdir={default_repo} git push",
        "env -C {default_repo} sh -c 'git push'",
        "bash -lc 'git push origin {default}'",
        "sh -ec 'git push origin {default}'",
        "bash -o pipefail -xc 'git push origin {default}'",
        "bash --login -c 'git push origin {default}'",
        "git push origin HEAD:heads/{default}",
        "git push origin heads/{default}",
        "timeout 60 git push origin {default}",
        "timeout -k 5 --foreground 60 git push origin {default}",
        "nice git push origin {default}",
        "nice -n 5 git push origin {default}",
        "ionice -c 3 git push origin {default}",
        "stdbuf -o L git push origin {default}",
        "xargs git push origin {default} < /dev/null",
        "xargs -I x git push origin {default}",
        "setsid git push origin {default}",
        "doas -u root git push origin {default}",
        "echo issue#3 && git push origin {default}",
        "echo a#b c#d; git push origin {default}",
        "pushd {default_repo} && git push",
        "git -c push.default=matching push origin",
        "git -c remote.origin.push=HEAD:{default} push origin",
        "git --config-env=push.default=MODE push origin",
        (
            "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=push.default"
            " GIT_CONFIG_VALUE_0=matching git push origin"
        ),
    ],
)
def test_push_in_shell_constructs_and_config_overrides_is_blocked(
    hook, issue_repo, default_repo, default_branch, monkeypatch, command
):
    monkeypatch.setenv("MODE", "matching")
    command = command.format(default=default_branch, default_repo=default_repo)
    assert hook.is_blocked(command, issue_repo) == hook.DEFAULT_BRANCH


@pytest.mark.parametrize(
    "command",
    [
        "{{ git push origin issue-64-x; }}",
        "if true; then git push origin issue-64-x; fi",
        "bash -c 'git push origin issue-64-x'",
        'echo "$(git log)"',
        "sudo -u root git status",
        "git -c push.default=simple push origin",
        "GIT_TRACE=1 git push origin",
        "env -C {issue_repo} git push",
        "bash -lc 'git push origin issue-64-x'",
        "timeout 60 git push origin issue-64-x",
        "echo issue#3 && git push origin issue-64-x",
        "echo hi # && git push origin main",
        "echo hi;# git push origin main",
    ],
)
def test_other_shell_constructs_are_allowed(hook, issue_repo, command):
    command = command.format(issue_repo=issue_repo)
    assert hook.is_blocked(command, issue_repo) is None


def test_aliases_are_expanded(hook, issue_repo, default_branch):
    git(issue_repo, "config", "alias.p", "push")
    git(issue_repo, "config", "alias.pp", "p origin")
    git(issue_repo, "config", "alias.sp", f"!git push origin {default_branch}")
    git(issue_repo, "config", "alias.st", "status")
    assert hook.is_blocked(f"git p origin {default_branch}", issue_repo)
    assert hook.is_blocked(f"git pp {default_branch}", issue_repo)
    assert hook.is_blocked("git sp", issue_repo)
    assert not hook.is_blocked("git p origin issue-64-x", issue_repo)
    assert not hook.is_blocked("git st", issue_repo)


@pytest.mark.parametrize(
    ("refspec", "blocked"),
    [
        ("refs/heads/issue-64-x:refs/heads/{default}", True),
        ("+refs/heads/issue-*:refs/heads/{default}", True),
        ("refs/heads/*:refs/heads/review/*", False),
        # git maps only configured sources written as full refs.
        ("HEAD:refs/heads/{default}", False),
        ("issue-64-x:{default}", False),
    ],
)
def test_refspec_without_destination_follows_remote_push_config(
    hook, issue_repo, default_branch, refspec, blocked
):
    git(
        issue_repo,
        "config",
        "remote.origin.push",
        refspec.format(default=default_branch),
    )
    for command in (
        "git push origin issue-64-x",
        "git push origin refs/heads/issue-64-x",
    ):
        assert bool(hook.is_blocked(command, issue_repo)) is blocked
    assert not hook.is_blocked("git push origin issue-64-x:issue-64-x", issue_repo)


def test_command_variables_cannot_change_which_git_the_hook_runs(
    hook, issue_repo, default_branch, tmp_path
):
    planted = tmp_path / "tools"
    planted.mkdir()
    marker = tmp_path / "ran"
    (planted / "git").write_text(f"#!/bin/sh\ntouch {marker}\n")
    (planted / "git").chmod(0o755)
    command = f"PATH={planted}:/nonexistent git push origin {default_branch}"
    assert hook.is_blocked(command, issue_repo) == hook.DEFAULT_BRANCH
    assert not hook.is_blocked(f"PATH={planted} git log", issue_repo)
    assert not hook.is_blocked(f"LD_PRELOAD=/x.so PATH={planted} git p", issue_repo)
    assert not marker.exists()


def test_hook_error_blocks_push_only(hook, issue_repo, monkeypatch, capsys):
    def run(command):
        hook_input = {"cwd": issue_repo, "tool_input": {"command": command}}
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(hook_input)))
        try:
            hook.main()
        except SystemExit as exit:
            return exit.code
        return 0

    # Every git call of the hook raises FileNotFoundError.
    monkeypatch.setattr(hook, "GIT", "/nonexistent/git")
    assert run("git push origin issue-64-x") == 2
    assert capsys.readouterr().err.startswith("push hook failed")
    assert run("git status") == 0


def test_tags_only_push_on_default_branch_is_allowed(hook, default_repo):
    assert not hook.is_blocked("git push --tags", default_repo)
    assert not hook.is_blocked("git push origin --tags", default_repo)
    assert hook.is_blocked("git push --follow-tags", default_repo)
    assert hook.is_blocked("git push --tags origin HEAD", default_repo)
