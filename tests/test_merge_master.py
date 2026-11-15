import pytest
from conftest import commit, git, load_script, run_main


@pytest.fixture
def script():
    return load_script("merge-master.py")


def test_current_when_branch_contains_master(script, capsys, repos):
    _, clone = repos
    head = commit(clone, "feature", "feature")

    assert run_main(script, capsys) == ("current", 0)
    assert git(clone, "rev-parse", "HEAD") == head


def test_merges_master_without_pushing(script, capsys, repos):
    upstream, clone = repos
    commit(clone, "feature", "feature")
    master = commit(upstream, "other", "other")
    git(upstream, "push", "origin", "master")

    assert run_main(script, capsys) == ("merged", 0)
    assert len(git(clone, "rev-parse", "HEAD^@").split()) == 2
    git(clone, "merge-base", "--is-ancestor", master, "HEAD")
    assert git(clone, "ls-remote", "origin", "feature") == ""


def test_conflict_aborts_merge(script, capsys, repos):
    upstream, clone = repos
    head = commit(clone, "same", "feature")
    commit(upstream, "same", "master")
    git(upstream, "push", "origin", "master")

    assert run_main(script, capsys) == ("conflict", 1)
    assert git(clone, "rev-parse", "HEAD") == head
    assert git(clone, "status", "--porcelain") == ""


def test_rejects_arguments(script):
    with pytest.raises(SystemExit) as exit:
        script.main(["66"])

    assert exit.value.code == script.__doc__
