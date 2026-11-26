import subprocess

import pytest
from conftest import PIPELINE_URL, ROOT, commit, git, write_executable

SUB = ".claude/skills/pipeline"
PIN = ".claude/pipeline-release"
BUMP = "7\tabc\tBump pipeline to v2\thttps://github.com/o/app/pull/7"


@pytest.fixture
def host(tmp_path, pipeline_releases):
    """A gate stub for user app, the stubs of install-gate.sh and the Telegram
    script of the project; the releases at PIPELINE_URL. run() runs update-host.sh."""
    root, stubs, home = tmp_path / "root", tmp_path / "stubs", tmp_path / "home"
    for path in (stubs, home, root / "etc/pipeline-gate/projects/app"):
        path.mkdir(parents=True)
    store = root / "etc/pipeline-gate/projects/app"
    (store / "repo").write_text("o/app\n")
    (store / "token").write_text("github_pat_x\n")
    (store / "review-key").write_text("k" * 64 + "\n")
    state = tmp_path / "state"
    state.mkdir()
    for name, content in {
        "prs": BUMP,
        "files": PIN,
        "have": "v2",
        "pinned": "v1",
        "newest": "v2",
        "stable": "true",
        "vetoes": "0",
        "merge-failures": "",
        "pending": "1",
    }.items():
        (state / name).write_text(content + "\n" if content else "")
    gate = root / "opt/pipeline/gate"
    gate.parent.mkdir(parents=True)
    (root / "opt/pipeline/pipeline-repo").write_text(
        PIPELINE_URL.removeprefix("https://github.com/") + "\n"
    )
    write_executable(
        gate,
        f"""echo "$*" >> {state}/gate.log
case "$1 $2 $3" in
  "gh pr list") case "$*" in *closed*) [ ! -e {state}/closed-fails ] || exit 1; cat {state}/vetoes ;; *) cat {state}/prs ;; esac ;;
  "gh pr view")
    [ ! -e {state}/view-fails ] || exit 1
    case "$*" in *files*) cat {state}/files ;; *) echo "- Notes of v2" ;; esac ;;
  "gh api "*) case "$*" in *ref=HEAD*) cat {state}/pinned ;; *) cat {state}/have ;; esac ;;
  "gh run list") cat {state}/pending ;;
  "gh release list") cat {state}/newest ;;
  "gh release view") cat {state}/stable ;;
  "review --manual "*) touch {state}/approved ;;
  "merge "*)
    if [ ! -e {state}/approved ]; then
      echo "gate: no attested approve on $3" >&2
      exit 1
    fi
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
    write_executable(stubs / "systemctl", "")
    project = tmp_path / "project"
    units = home / ".config/systemd/user"
    units.mkdir(parents=True)
    (units / "autopilot-app.service").write_text(f"WorkingDirectory={project}\n")
    send = project / SUB / "bin/telegram-send.py"
    send.parent.mkdir(parents=True)
    write_executable(
        send,
        f"[ ! -e {state}/telegram-fails ] || exit 1\n"
        f'cat >> {state}/telegram.log; echo "cwd $PWD" >> {state}/telegram.log',
    )

    def run(*args, user="app", answer="y\n"):
        return subprocess.run(
            [str(ROOT / "host/update-host.sh"), *args, user],
            input=answer,
            env={
                "PATH": f"{stubs}:/usr/bin:/bin",
                "HOME": str(home),
                "GATE_ROOT": str(root),
                "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
                "GIT_CONFIG_NOSYSTEM": "1",
            },
            capture_output=True,
            text=True,
            check=False,
        )

    run.home = home
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
    assert merges(state) == ["merge 7 abc"] * 3


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
    assert len(merges(state)) == 3


@pytest.mark.parametrize(
    ("refusal", "pending"),
    [
        ("gate: #7 is not open", "1"),
        ("gate: 1 review threads are open; runs not passed: CI", "1"),
        ("gate: runs not passed: CI", "0"),
        ("gate: gh pr merge failed: Pull request is not mergeable", "1"),
    ],
    ids=["closed", "threads_and_runs", "failed_runs", "conflict"],
)
def test_lasting_refusal_stops_before_the_gate_is_installed(host, refusal, pending):
    run, state, root = host
    (state / "merge-always").write_text(refusal + "\n")
    (state / "pending").write_text(pending + "\n")

    result = run()

    assert result.returncode == 1
    assert f"merging #7 failed: {refusal}" in result.stderr
    assert len(merges(state)) == 2
    assert "#!/usr/bin/env bash" in (root / "opt/pipeline/gate").read_text()


def test_merge_gives_up_after_30_minutes(host):
    run, state, root = host
    (state / "merge-always").write_text("gate: runs not passed: CI\n")

    result = run()

    assert result.returncode == 1
    assert "#7 still not mergeable after 30 minutes" in result.stderr
    assert len(merges(state)) == 61
    assert "#!/usr/bin/env bash" in (root / "opt/pipeline/gate").read_text()


def telegram(state):
    return log(state, "telegram")


def test_installs_the_claude_code_version_of_the_release(host):
    run, state, _root = host
    claude = run.home / ".local/bin/claude"
    claude.parent.mkdir(parents=True, exist_ok=True)
    write_executable(
        claude,
        f'[ "$1" = --version ] && echo "0.0.1 (Claude Code)" || echo "$*" >> {state}/claude.log',
    )
    version = next(
        line.split("=", 1)[1]
        for line in (ROOT / "host/versions.sh").read_text().splitlines()
        if line.startswith("claude_code=")
    )

    result = run()

    assert result.returncode == 0, result.stderr
    # The stub sudo keeps HOME, so both accounts reach the same stub.
    assert log(state, "claude") == [f"install {version}"] * 2


@pytest.fixture
def app_remote(tmp_path, host):
    """o/app as a clone of the pipeline pinned to v1, and the gh of the user for bump.sh,
    in ~/.local/bin as install-gate.sh puts it, not on the PATH of root."""
    work, remote = tmp_path / "app-work", tmp_path / "app.git"
    git(tmp_path, "clone", "-q", PIPELINE_URL, str(work))
    commit(work, PIN, "v1\n")
    git(tmp_path, "init", "-q", "--bare", str(remote))
    git(work, "push", "-q", "--tags", str(remote), "HEAD")
    with (tmp_path / "gitconfig").open("a") as config:
        config.write(f'[url "{remote}"]\n\tinsteadOf = https://github.com/o/app\n')
    # Only the working tree of the autopilot holds its git identity.
    project = tmp_path / "project"
    git(project, "init", "-q")
    git(project, "config", "user.name", "autopilot")
    git(project, "config", "user.email", "autopilot@host")
    (host[0].home / ".local/bin").mkdir(parents=True, exist_ok=True)
    write_executable(
        host[0].home / ".local/bin/gh",
        f"""echo "$*" >> {tmp_path}/state/gh.log
case "$1 $2" in
  "release list") echo v2 ;;
  "release view") echo "- Notes of v2" ;;
esac""",
    )
    return remote


def test_auto_opens_the_bump_to_the_newest_release(host, app_remote):
    run, state, _root = host
    (state / "prs").write_text("")

    result = run("--auto")

    assert result.returncode == 0, result.stderr
    assert git(app_remote, "show", f"bump-pipeline-v2:{PIN}").strip() == "v2"
    assert (
        git(app_remote, "log", "-1", "--format=%an", "bump-pipeline-v2") == "autopilot"
    )
    assert any(line.startswith("pr create") for line in log(state, "gh"))
    assert not approved(state)


@pytest.mark.parametrize(
    ("pinned", "vetoes"), [("v2", "0"), ("v1", "1")], ids=["current", "vetoed"]
)
def test_auto_opens_no_bump(host, pinned, vetoes):
    run, state, _root = host
    (state / "prs").write_text("")
    (state / "pinned").write_text(pinned + "\n")
    (state / "vetoes").write_text(vetoes + "\n")

    result = run("--auto")

    assert result.returncode == 0, result.stderr
    assert not log(state, "gh")
    assert not any("git clone" in line for line in log(state, "sudo"))


def test_auto_announces_first_and_merges_12_hours_later(host, tmp_path):
    run, state, root = host
    announced = root / "var/lib/pipeline-update/app-abc"

    first = run("--auto", answer="")
    soon = run("--auto", answer="")

    assert (first.returncode, soon.returncode) == (0, 0), first.stderr + soon.stderr
    assert not approved(state)
    assert (
        "Pipeline-Update auf v2 (https://github.com/o/app/pull/7) folgt ab"
        in (telegram(state)[0])
    )
    assert telegram(state)[1] == f"cwd {tmp_path / 'project'}"
    assert len(telegram(state)) == 2

    subprocess.run(["touch", "-d", "13 hours ago", str(announced)], check=True)
    later = run("--auto", answer="")

    assert later.returncode == 0, later.stderr
    assert approved(state)
    assert (root / "opt/pipeline/gate").read_text() == (
        ROOT / "host/gate.py"
    ).read_text()
    assert "Pipeline-Update auf v2 installiert" in telegram(state)[2]
    assert not announced.exists()


def test_auto_refuses_a_prerelease_and_reports_it_once(host):
    run, state, _root = host
    (state / "stable").write_text("false\n")

    first = run("--auto")
    second = run("--auto")

    assert (first.returncode, second.returncode) == (1, 1)
    assert "v2 is no published stable release" in first.stderr
    assert len([line for line in telegram(state) if "gescheitert" in line]) == 1
    assert not approved(state)


def test_auto_refuses_a_tag_off_the_default_branch(host, tmp_path):
    run, state, _root = host
    side = tmp_path / "side"
    git(tmp_path, "clone", "-q", PIPELINE_URL, str(side))
    commit(side, "side", "side")
    git(side, "tag", "v3")
    git(side, "push", "-q", "origin", "v3")
    (state / "prs").write_text(BUMP.replace("v2", "v3") + "\n")
    (state / "have").write_text("v3\n")
    (state / "newest").write_text("v3\n")

    result = run("--auto")

    assert result.returncode == 1
    assert "v3 is not on the default branch" in result.stderr
    assert not approved(state)


def test_existing_approve_is_not_posted_again(host):
    run, state, _root = host
    (state / "approved").touch()

    result = run()

    assert result.returncode == 0, result.stderr
    assert merges(state) == ["merge 7 abc"]
    assert not approved(state)


@pytest.mark.parametrize(
    ("newest", "vetoes", "error"),
    [
        ("v3", "0", "#7 bumps to v2, not to the newest release v3"),
        ("v2", "1", "#7 bumps to v2, which a closed bump pull request vetoed"),
    ],
    ids=["older", "vetoed"],
)
def test_auto_takes_only_the_newest_unvetoed_release(host, newest, vetoes, error):
    run, state, _root = host
    (state / "newest").write_text(newest + "\n")
    (state / "vetoes").write_text(vetoes + "\n")

    result = run("--auto")

    assert result.returncode == 1
    assert error in result.stderr
    assert not approved(state)


def test_auto_waits_only_after_a_sent_announcement(host):
    run, state, root = host
    (state / "telegram-fails").touch()

    result = run("--auto")

    assert result.returncode == 1
    assert "announcing v2 via Telegram failed" in result.stderr
    assert not (root / "var/lib/pipeline-update/app-abc").exists()


def test_auto_reports_an_unexpected_failure_once(host):
    run, state, _root = host
    (state / "view-fails").touch()

    first = run("--auto")
    second = run("--auto")

    assert (first.returncode, second.returncode) == (1, 1)
    assert "failed, see journalctl -u pipeline-update@app" in first.stderr
    assert len([line for line in telegram(state) if "gescheitert" in line]) == 1


def test_auto_needs_the_autopilot_service_for_telegram(host):
    run, state, _root = host
    for unit in (run.home / ".config/systemd/user").iterdir():
        unit.unlink()

    result = run("--auto")

    assert result.returncode == 1
    assert "no autopilot service of app" in result.stderr
    assert not log(state, "gate")


def test_auto_reports_a_failed_veto_query(host):
    run, state, _root = host
    (state / "prs").write_text("")
    (state / "closed-fails").touch()

    first = run("--auto")
    second = run("--auto")

    assert (first.returncode, second.returncode) == (1, 1)
    assert "listing the closed bump pull requests of o/app failed" in first.stderr
    assert len([line for line in telegram(state) if "gescheitert" in line]) == 1
    assert not any("git clone" in line for line in log(state, "sudo"))
