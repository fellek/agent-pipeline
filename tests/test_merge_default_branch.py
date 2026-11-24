import pytest
from conftest import commit, git, load_script, run_main


@pytest.fixture
def script():
    return load_script("merge-default-branch.py")


def test_current_when_branch_contains_default_branch(script, capsys, repos):
    _, clone = repos
    head = commit(clone, "feature", "feature")

    assert run_main(script, capsys) == ("current", 0)
    assert git(clone, "rev-parse", "HEAD") == head


def test_merges_default_branch_without_pushing(script, capsys, repos, default_branch):
    upstream, clone = repos
    commit(clone, "feature", "feature")
    merged = commit(upstream, "other", "other")
    git(upstream, "push", "origin", default_branch)

    assert run_main(script, capsys) == ("merged", 0)
    assert len(git(clone, "rev-parse", "HEAD^@").split()) == 2
    git(clone, "merge-base", "--is-ancestor", merged, "HEAD")
    assert git(clone, "ls-remote", "origin", "feature") == ""


def test_ignores_other_branches(script, capsys, repos, other_branch):
    upstream, _ = repos
    git(upstream, "switch", "-c", other_branch)
    commit(upstream, "other", "other")
    git(upstream, "push", "origin", other_branch)

    assert run_main(script, capsys) == ("current", 0)


def test_conflict_aborts_merge(script, capsys, repos, default_branch):
    upstream, clone = repos
    head = commit(clone, "same", "feature")
    commit(upstream, "same", "default")
    git(upstream, "push", "origin", default_branch)

    assert run_main(script, capsys) == ("conflict", 1)
    assert git(clone, "rev-parse", "HEAD") == head
    assert git(clone, "status", "--porcelain") == ""


def test_rejects_arguments(script):
    with pytest.raises(SystemExit) as exit:
        script.main(["66"])

    assert exit.value.code == script.__doc__
