import json
import os
import shutil
import subprocess

import pytest
from conftest import PIPELINE_URL, git, load_script, script_path, write_executable

SCRIPT = script_path("init-project.sh")
CHECK = ".claude/skills/pipeline/bin/check-project.py"
COPIED = (
    "CLAUDE.md",
    ".claude/settings.json",
    ".claude/rules/project.md",
    ".github/workflows/agent-review.yml",
    ".github/workflows/agent-review-sync.yml",
)


@pytest.fixture
def app(tmp_path, monkeypatch, pipeline_releases):
    """An empty repository, with a gh stub on PATH that records the labels."""
    path = tmp_path / "app"
    path.mkdir()
    git(path, "init", "-q")
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    write_executable(
        stubs / "gh",
        f"""echo "$*" >> {tmp_path}/gh_calls
case "$1 $2" in
  "label list") cat {tmp_path}/labels 2>/dev/null || true ;;
  "label create") echo "$3" >> {tmp_path}/labels ;;
esac""",
    )
    monkeypatch.setenv("PATH", f"{stubs}:{os.environ['PATH']}")
    return path


def labels(app):
    return app.parent / "labels"


def init_project(cwd, *args):
    return subprocess.run(
        [str(SCRIPT), *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def test_sets_up_empty_repository(app, pipeline_releases):
    result = init_project(app, "v1")

    assert result.returncode == 0, result.stderr
    head = git(app / ".claude/skills/pipeline", "rev-parse", "HEAD")
    assert head == pipeline_releases["v1"]
    assert git(app, "config", "-f", ".gitmodules", "--get-regexp", "url") == (
        f"submodule..claude/skills/pipeline.url {PIPELINE_URL}"
    )
    assert git(app, "config", "submodule.recurse") == "true"
    for name in COPIED:
        assert (app / name).is_file(), name
    assert {".pipeline/", ".claude/settings.local.json"} <= set(
        (app / ".gitignore").read_text().splitlines()
    )
    assert "Automatically delete head branches" in result.stdout
    assert "ruleset" in result.stdout
    assert "allow list" in result.stdout


def test_result_passes_check_project(app):
    init_project(app, "v1")

    result = subprocess.run(
        [str(app / CHECK)], cwd=app, check=False, capture_output=True, text=True
    )

    assert (result.returncode, result.stderr) == (0, "")


@pytest.mark.skipif(shutil.which("claude") is None, reason="claude is not installed")
def test_result_loads_plugin(app, tmp_path):
    init_project(app, "v1")
    home = tmp_path / "home"
    home.mkdir()
    trusted = {"projects": {str(app.resolve()): {"hasTrustDialogAccepted": True}}}
    (home / ".claude.json").write_text(json.dumps(trusted))

    result = subprocess.run(
        ["claude", "plugin", "list"],
        cwd=app,
        env={"PATH": os.environ["PATH"], "HOME": str(home)},
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    entry = result.stdout.split("pipeline@skills-dir", 1)[1]
    assert "Path: ./.claude/skills/pipeline" in entry
    assert "loaded" in entry.split("\n\n", 1)[0]


def test_creates_status_labels(app):
    init_project(app, "v1")

    created = set(labels(app).read_text().splitlines())
    status = load_script("autopilot-poll.py").STATUS_LABELS
    assert created == status | {"followup"}


def test_keeps_existing_files_labels_and_entries(app):
    (app / "CLAUDE.md").write_text("# App\n")
    (app / ".gitignore").write_text("node_modules/\n.pipeline/")
    labels(app).write_text("ready\n")

    result = init_project(app, "v1")

    assert result.returncode == 0, result.stderr
    assert (app / "CLAUDE.md").read_text() == "# App\n"
    assert "kept CLAUDE.md" in result.stdout
    assert (app / ".gitignore").read_text().splitlines()[:2] == [
        "node_modules/",
        ".pipeline/",
    ]
    assert (app / ".gitignore").read_text().count(".pipeline/") == 1
    assert labels(app).read_text().count("ready") == 1


def test_second_run_changes_nothing(app):
    init_project(app, "v1")
    before = {name: (app / name).read_text() for name in (*COPIED, ".gitignore")}
    before_labels = labels(app).read_text()

    result = init_project(app, "v2")

    assert result.returncode == 0, result.stderr
    assert "kept .claude/skills/pipeline" in result.stdout
    assert {name: (app / name).read_text() for name in before} == before
    assert labels(app).read_text() == before_labels


def test_unknown_tag_adds_no_submodule(app):
    result = init_project(app, "v9")

    assert result.returncode == 1
    assert "tag v9 not found" in result.stderr
    assert not (app / ".claude").exists()
    assert not (app / ".gitmodules").exists()


def test_runs_only_in_repository_root(app):
    (app / "sub").mkdir()

    result = init_project(app / "sub", "v1")

    assert result.returncode == 1
    assert "project root" in result.stderr
    assert not (app / ".gitmodules").exists()


@pytest.mark.parametrize("args", [(), ("v1", "v2"), ("",)])
def test_rejects_bad_arguments(app, args):
    assert init_project(app, *args).returncode == 1
