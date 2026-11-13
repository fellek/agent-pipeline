import subprocess

import pytest
from conftest import load_script


@pytest.fixture
def script():
    return load_script("merge-master.py")


def git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


def commit(cwd, name, content):
    (cwd / name).write_text(content)
    git(cwd, "add", name)
    git(cwd, "commit", "-m", name)
    return git(cwd, "rev-parse", "HEAD")


@pytest.fixture
def repos(tmp_path, monkeypatch):
    for key, value in {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "GIT_CONFIG_GLOBAL": "/dev/null",
    }.items():
        monkeypatch.setenv(key, value)
    remote, upstream, clone = (tmp_path / n for n in ("remote", "upstream", "clone"))
    git(tmp_path, "init", "--bare", "-b", "master", str(remote))
    git(tmp_path, "clone", str(remote), str(upstream))
    commit(upstream, "base", "base")
    git(upstream, "push", "origin", "master")
    git(tmp_path, "clone", str(remote), str(clone))
    git(clone, "switch", "-c", "feature")
    monkeypatch.chdir(clone)
    return upstream, clone


def run(script, capsys):
    try:
        script.main([])
        code = 0
    except SystemExit as exit:
        code = exit.code
    return capsys.readouterr().out.strip(), code


def test_current_when_branch_contains_master(script, capsys, repos):
    _, clone = repos
    head = commit(clone, "feature", "feature")

    assert run(script, capsys) == ("current", 0)
    assert git(clone, "rev-parse", "HEAD") == head


def test_merges_master_without_pushing(script, capsys, repos):
    upstream, clone = repos
    commit(clone, "feature", "feature")
    master = commit(upstream, "other", "other")
    git(upstream, "push", "origin", "master")

    assert run(script, capsys) == ("merged", 0)
    assert len(git(clone, "rev-parse", "HEAD^@").split()) == 2
    git(clone, "merge-base", "--is-ancestor", master, "HEAD")
    assert git(clone, "ls-remote", "origin", "feature") == ""


def test_conflict_aborts_merge(script, capsys, repos):
    upstream, clone = repos
    head = commit(clone, "same", "feature")
    commit(upstream, "same", "master")
    git(upstream, "push", "origin", "master")

    assert run(script, capsys) == ("conflict", 1)
    assert git(clone, "rev-parse", "HEAD") == head
    assert git(clone, "status", "--porcelain") == ""


def test_rejects_arguments(script):
    with pytest.raises(SystemExit) as exit:
        script.main(["66"])

    assert exit.value.code == script.__doc__
