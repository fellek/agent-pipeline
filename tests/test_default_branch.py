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
