import re

import pytest
from conftest import commit, git, load_script, run_main


@pytest.fixture
def script():
    return load_script("cleanup-tree.py")


@pytest.fixture
def clone(repos):
    return repos[1]


def test_commits_changes_onto_cleanup_branch(script, capsys, clone):
    (clone / "base").write_text("changed")
    (clone / "new").write_text("new")

    output, code = run_main(script, capsys, "7")

    assert code == 0
    assert re.fullmatch(r"cleanup/7-\d{8}T\d{6}Z", output)
    assert git(clone, "show", f"{output}:base") == "changed"
    assert git(clone, "show", f"{output}:new") == "new"


def test_returns_to_unchanged_original_branch(script, capsys, clone):
    head = commit(clone, "feature", "feature")
    (clone / "base").write_text("changed")

    run_main(script, capsys, "7")

    assert git(clone, "branch", "--show-current") == "feature"
    assert git(clone, "rev-parse", "HEAD") == head
    assert git(clone, "status", "--porcelain") == ""


def test_neither_pushes_nor_stashes(script, capsys, clone):
    (clone / "base").write_text("changed")

    output, _ = run_main(script, capsys, "7")

    assert git(clone, "ls-remote", "origin", output) == ""
    assert git(clone, "stash", "list") == ""


def test_clean_tree_has_nothing_to_commit(script, capsys, clone):
    assert run_main(script, capsys, "7") == ("clean", 1)
    assert git(clone, "branch", "--list", "cleanup/*") == ""


@pytest.mark.parametrize("argv", [[], ["7", "8"], ["x"]])
def test_rejects_bad_arguments(script, argv):
    with pytest.raises(SystemExit) as exit:
        script.main(argv)

    assert exit.value.code == script.__doc__
