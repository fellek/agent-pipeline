import getpass
import subprocess

import pytest
from conftest import PIPELINE_URL, ROOT, git, write_executable

SUB = ".claude/skills/pipeline"
PIN = ".claude/pipeline-release"
BUMP = "7\tabc\tBump pipeline to v2\thttps://github.com/o/app/pull/7"


@pytest.fixture
def host(tmp_path, pipeline_releases):
    """The maintainer's clone at v1, a gate stub for user app and the stubs of
    install-gate.sh; run() runs update-host.sh of the clone."""
    clone = tmp_path / "maintainer"
    git(tmp_path, "clone", "-q", "--branch", "v1", PIPELINE_URL, str(clone))
    root, stubs, home = tmp_path / "root", tmp_path / "stubs", tmp_path / "home"
    for path in (stubs, home, root / "etc/pipeline-gate/projects/app"):
        path.mkdir(parents=True)
    store = root / "etc/pipeline-gate/projects/app"
    (store / "repo").write_text("o/app\n")
    (store / "token").write_text("github_pat_x\n")
    (store / "review-key").write_text("k" * 64 + "\n")
    state = tmp_path / "state"
    state.mkdir()
    (state / "prs").write_text(BUMP + "\n")
    (state / "files").write_text(PIN + "\n")
    (state / "have").write_text("v2\n")
    (state / "merge-failures").write_text("")
    (state / "pending").write_text("1\n")
    gate = root / "opt/pipeline/gate"
    gate.parent.mkdir(parents=True)
    write_executable(
        gate,
        f"""echo "$*" >> {state}/gate.log
case "$1 $2 $3" in
  "gh pr list") cat {state}/prs ;;
  "gh pr view") case "$*" in *files*) cat {state}/files ;; *) echo "- Notes of v2" ;; esac ;;
  "gh api "*) cat {state}/have ;;
  "gh run list") cat {state}/pending ;;
  "merge "*)
    if [ -s {state}/merge-always ]; then
      cat {state}/merge-always >&2
      exit 1
    fi
    if [ -s {state}/merge-failures ]; then
      head -1 {state}/merge-failures >&2
      sed -i 1d {state}/merge-failures
      exit 1
    fi ;;
esac""",
    )
    write_executable(
        stubs / "sudo",
        f"""echo "$*" >> {state}/sudo.log
while [ "${{1:0:1}}" = - ]; do case $1 in -u) shift 2 ;; *) shift ;; esac; done
exec "$@\"""",
    )
    write_executable(stubs / "sleep", "")
    write_executable(
        stubs / "getent",
        f'case "$2" in app) echo "app:x:1001:1001::{home}:/bin/bash" ;; *) exit 0 ;; esac',
    )
    write_executable(stubs / "chown", "")
    write_executable(stubs / "visudo", "")

    def run(user="app", answer="y\n"):
        return subprocess.run(
            [str(clone / "host/update-host.sh"), user],
            input=answer,
            env={
                "PATH": f"{stubs}:/usr/bin:/bin",
                "GATE_ROOT": str(root),
                "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
            },
            capture_output=True,
            text=True,
            check=False,
        )

    return run, state, root


def log(state, name):
    path = state / f"{name}.log"
    return path.read_text().splitlines() if path.exists() else []


def approved(state):
    return any(line.startswith("review --manual") for line in log(state, "gate"))


def test_approves_merges_and_installs_the_gate_of_the_release(host):
    run, state, root = host

    result = run()

    assert result.returncode == 0, result.stderr
    assert "- Notes of v2" in result.stdout
    gate = f"{root}/opt/pipeline/gate"
    sudo = log(state, "sudo")
    # Only root's own call reaches the gate as root; the others run as the user.
    assert f"-u pipeline-gate {gate} review --manual app 7 abc approve" in sudo
    assert f"-u app sudo -n -u pipeline-gate {gate} merge 7 abc" in sudo
    assert "gh api repos/o/app/contents/.claude/pipeline-release?ref=abc" in " ".join(
        log(state, "gate")
    )
    assert (root / "opt/pipeline/gate").read_text() == (
        ROOT / "host/gate.py"
    ).read_text()
    assert (root / "etc/pipeline-gate/projects/app/token").read_text() == (
        "github_pat_x\n"
    )


def test_submodule_must_point_at_the_tag_and_merge_waits_for_runs(
    host, pipeline_releases
):
    run, state, _root = host
    (state / "files").write_text(SUB + "\n")
    (state / "have").write_text(pipeline_releases["v2"] + "\n")
    (state / "merge-failures").write_text("gate: runs not passed: CI\n")

    result = run()

    assert result.returncode == 0, result.stderr
    assert "waiting: gate: runs not passed: CI" in result.stdout
    assert merges(state) == ["merge 7 abc", "merge 7 abc"]


@pytest.mark.parametrize(
    ("files", "have", "error"),
    [
        (PIN, "v3", "#7 pins v3, not v2"),
        (f"{PIN}\nREADME.md", "v2", "#7 changes more than the pinned release"),
        (SUB, "0" * 40, f"#7 pins {'0' * 40}, not v2"),
    ],
    ids=["other_tag", "other_files", "other_commit"],
)
def test_refuses_a_bump_that_pins_anything_else(host, files, have, error):
    run, state, _root = host
    (state / "files").write_text(files + "\n")
    (state / "have").write_text(have + "\n")

    result = run()

    assert result.returncode == 1
    assert error in result.stderr
    assert not approved(state)


@pytest.mark.parametrize(
    ("prs", "error"),
    [
        ("", "o/app has no open bump pull request"),
        (f"{BUMP}\n{BUMP}", "several open bump pull requests"),
        ("7\tabc\tAdd a feature\turl", "#7 is no bump"),
    ],
    ids=["none", "several", "title"],
)
def test_needs_exactly_one_bump(host, prs, error):
    run, state, _root = host
    (state / "prs").write_text(prs + "\n" if prs else "")

    result = run()

    assert result.returncode == 1
    assert error in result.stderr
    assert not approved(state)


def test_does_nothing_without_yes(host):
    run, state, root = host

    result = run(answer="n\n")

    assert result.returncode == 1
    assert "nothing done" in result.stderr
    assert not approved(state)
    assert "#!/usr/bin/env bash" in (root / "opt/pipeline/gate").read_text()


def merges(state):
    return [line for line in log(state, "gate") if line.startswith("merge")]


def test_merge_waits_for_a_required_status_check(host):
    run, state, _root = host
    (state / "merge-failures").write_text(
        "gate: gh pr merge failed: Required status check agent-review is expected\n"
    )

    result = run()

    assert result.returncode == 0, result.stderr
    assert len(merges(state)) == 2


@pytest.mark.parametrize(
    ("refusal", "pending"),
    [
        ("gate: no attested approve on abc", "1"),
        ("gate: 1 review threads are open; runs not passed: CI", "1"),
        ("gate: runs not passed: CI", "0"),
        ("gate: gh pr merge failed: Pull request is not mergeable", "1"),
    ],
    ids=["no_approve", "threads_and_runs", "failed_runs", "conflict"],
)
def test_lasting_refusal_stops_before_the_gate_is_installed(host, refusal, pending):
    run, state, root = host
    (state / "merge-always").write_text(refusal + "\n")
    (state / "pending").write_text(pending + "\n")

    result = run()

    assert result.returncode == 1
    assert f"merging #7 failed: {refusal}" in result.stderr
    assert len(merges(state)) == 1
    assert "#!/usr/bin/env bash" in (root / "opt/pipeline/gate").read_text()


def test_merge_gives_up_after_30_minutes(host):
    run, state, root = host
    (state / "merge-always").write_text("gate: runs not passed: CI\n")

    result = run()

    assert result.returncode == 1
    assert "#7 still not mergeable after 30 minutes" in result.stderr
    assert len(merges(state)) == 60
    assert "#!/usr/bin/env bash" in (root / "opt/pipeline/gate").read_text()


def test_refuses_a_clone_of_the_autopilot_user(host):
    run, _state, root = host
    me = getpass.getuser()
    store = root / "etc/pipeline-gate/projects" / me
    store.mkdir()
    (store / "repo").write_text("o/app\n")

    result = run(user=me)

    assert result.returncode == 1
    assert "run the maintainer's clone of the pipeline" in result.stderr
