import pytest
from conftest import commit, git, load_script, run_main


@pytest.fixture
def script():
    return load_script("leave-branch.py")


def remote_head(clone, branch):
    return git(clone, "ls-remote", "origin", branch).split("\t")[0]


def test_clean_when_branch_is_on_origin(script, capsys, repos):
    _, clone = repos
    head = commit(clone, "feature", "feature")
    git(clone, "push", "origin", "feature")

    assert run_main(script, capsys, "feature") == ("clean", 0)
    assert remote_head(clone, "feature") == head


@pytest.mark.parametrize("change", ["base", "untracked"])
def test_dirty_tree_is_not_pushed(script, capsys, repos, change):
    _, clone = repos
    commit(clone, "feature", "feature")
    (clone / change).write_text("changed")

    assert run_main(script, capsys, "feature") == ("dirty", 1)
    assert remote_head(clone, "feature") == ""


def test_pushes_commits_ahead_of_origin(script, capsys, repos):
    _, clone = repos
    commit(clone, "one", "one")
    git(clone, "push", "origin", "feature")
    head = commit(clone, "two", "two")

    assert run_main(script, capsys, "feature") == ("pushed", 0)
    assert remote_head(clone, "feature") == head


def test_pushes_new_branch_with_commits(script, capsys, repos):
    _, clone = repos
    head = commit(clone, "feature", "feature")

    assert run_main(script, capsys, "feature") == ("pushed", 0)
    assert remote_head(clone, "feature") == head


def test_pushes_merge_of_master(script, capsys, repos):
    upstream, clone = repos
    commit(clone, "feature", "feature")
    git(clone, "push", "origin", "feature")
    commit(upstream, "other", "other")
    git(upstream, "push", "origin", "master")
    load_script("merge-master.py").main([])
    capsys.readouterr()
    head = git(clone, "rev-parse", "HEAD")

    assert run_main(script, capsys, "feature") == ("pushed", 0)
    assert remote_head(clone, "feature") == head


def test_branch_without_own_commits_is_not_pushed(script, capsys, repos):
    _, clone = repos

    assert run_main(script, capsys, "feature") == ("clean", 0)
    assert remote_head(clone, "feature") == ""


def test_diverged_branch_fails_to_push(script, capsys, repos):
    upstream, clone = repos
    git(upstream, "switch", "-c", "feature")
    commit(upstream, "theirs", "theirs")
    git(upstream, "push", "origin", "feature")
    commit(clone, "ours", "ours")

    output, code = run_main(script, capsys, "feature")

    assert output.startswith("push failed: ")
    assert code == 2


def test_never_pushes_master(script, capsys, repos):
    _, clone = repos
    git(clone, "switch", "master")
    before = remote_head(clone, "master")
    commit(clone, "local", "local")

    assert run_main(script, capsys, "master") == ("clean", 0)
    assert remote_head(clone, "master") == before


@pytest.mark.parametrize("argv", [[], ["a", "b"]])
def test_rejects_bad_arguments(script, argv):
    with pytest.raises(SystemExit) as exit:
        script.main(argv)

    assert exit.value.code == script.__doc__


def test_failed_fetch_is_reported(script, capsys, repos, tmp_path):
    _, clone = repos
    commit(clone, "feature", "feature")
    git(clone, "remote", "set-url", "origin", str(tmp_path / "missing"))

    output, code = run_main(script, capsys, "feature")
    assert output.startswith("push failed:")
    assert code == 2
