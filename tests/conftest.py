import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT_DIRS = ("bin", "host", "hooks")


def script_path(filename):
    matches = [
        path for folder in SCRIPT_DIRS if (path := ROOT / folder / filename).exists()
    ]
    if not matches:
        raise FileNotFoundError(f"{filename} not in {', '.join(SCRIPT_DIRS)}")
    if len(matches) > 1:
        raise RuntimeError(f"{filename} is ambiguous: {', '.join(map(str, matches))}")
    return matches[0]


def load_script(filename):
    spec = importlib.util.spec_from_file_location(
        Path(filename).stem.replace("-", "_"), script_path(filename)
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


def commit(cwd, name, content):
    path = cwd / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    git(cwd, "add", name)
    git(cwd, "commit", "-m", name)
    return git(cwd, "rev-parse", "HEAD")


@pytest.fixture
def git_identity(monkeypatch):
    for key, value in {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
    }.items():
        monkeypatch.setenv(key, value)


@pytest.fixture
def repos(tmp_path, monkeypatch, git_identity):
    remote, upstream, clone = (tmp_path / n for n in ("remote", "upstream", "clone"))
    git(tmp_path, "init", "--bare", "-b", "master", str(remote))
    git(tmp_path, "clone", str(remote), str(upstream))
    commit(upstream, "base", "base")
    git(upstream, "push", "origin", "master")
    git(tmp_path, "clone", str(remote), str(clone))
    git(clone, "switch", "-c", "feature")
    monkeypatch.chdir(clone)
    return upstream, clone


def run_main(script, capsys, *argv):
    try:
        script.main(list(argv))
        code = 0
    except SystemExit as error:
        code = exit_status(error.code)
    return capsys.readouterr().out.strip(), code


def exit_status(code):
    """Map a SystemExit code to the process exit status, as the interpreter does."""
    if code is None:
        return 0
    return code if isinstance(code, int) else 1


def write_executable(path, body):
    path.write_text(f"#!/usr/bin/env bash\n{body}\n")
    path.chmod(0o755)
