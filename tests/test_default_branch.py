import pytest
from conftest import git, load_script, run_main


@pytest.fixture
def script():
    return load_script("default-branch.py")


def test_prints_branch_of_origin_head(script, capsys, repos, default_branch):
    assert run_main(script, capsys) == (default_branch, 0)


def test_sets_missing_origin_head_from_remote(script, capsys, repos, default_branch):
    _, clone = repos
    git(clone, "remote", "set-head", "origin", "--delete")

    assert run_main(script, capsys) == (default_branch, 0)
    assert git(clone, "symbolic-ref", "refs/remotes/origin/HEAD") == (
        f"refs/remotes/origin/{default_branch}"
    )


def test_resets_origin_head_to_deleted_branch(script, capsys, repos, default_branch):
    # The default branch is renamed on the remote and the clone prunes the old one.
    upstream, clone = repos
    git(upstream, "push", "origin", f"{default_branch}:trunk")
    remote = git(clone, "remote", "get-url", "origin")
    git(remote, "symbolic-ref", "HEAD", "refs/heads/trunk")
    git(upstream, "push", "origin", "--delete", default_branch)
    git(clone, "fetch", "--prune", "origin")
    assert git(clone, "symbolic-ref", "refs/remotes/origin/HEAD") == (
        f"refs/remotes/origin/{default_branch}"
    )

    assert run_main(script, capsys) == ("trunk", 0)
    assert git(clone, "symbolic-ref", "refs/remotes/origin/HEAD") == (
        "refs/remotes/origin/trunk"
    )


def test_fails_without_origin(script, tmp_path, monkeypatch, git_identity):
    git(tmp_path, "init", "-b", "main")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exit:
        script.main([])

    assert "origin/HEAD is not set" in exit.value.code


def test_rejects_arguments(script):
    with pytest.raises(SystemExit) as exit:
        script.main(["main"])

    assert exit.value.code == script.__doc__


def test_ignores_local_branch_named_like_remote_branch(
    script, capsys, repos, default_branch
):
    # With a local branch origin/<x>, symbolic-ref --short prints remotes/origin/<x>.
    _, clone = repos
    git(clone, "branch", f"origin/{default_branch}")

    assert run_main(script, capsys) == (default_branch, 0)
