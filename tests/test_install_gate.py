import stat
import subprocess

import pytest
from conftest import ROOT, write_executable

SCRIPT = ROOT / "host" / "install-gate.sh"


@pytest.fixture
def install(tmp_path):
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    home = tmp_path / "home" / "app"
    home.mkdir(parents=True)
    root = tmp_path / "root"
    chowns = tmp_path / "chowns"
    write_executable(
        stubs / "getent",
        f'case "$2" in app) echo "app:x:1001:1001::{home}:/bin/bash" ;;'
        ' pipeline-gate) echo "pipeline-gate:x:999:999::/var/lib/pipeline-gate:/usr/sbin/nologin" ;;'
        " *) exit 2 ;; esac",
    )
    write_executable(stubs / "chown", f'echo "$1 $2" >> {chowns}')
    write_executable(stubs / "visudo", 'grep -q "NOPASSWD: /opt/pipeline/gate$" "$2"')
    write_executable(stubs / "useradd", "exit 1")
    write_executable(stubs / "systemctl", f'echo "$*" >> {tmp_path}/systemctl')

    def run(*args, token="github_pat_x\n"):
        result = subprocess.run(
            [str(SCRIPT), *args],
            input=token,
            env={"PATH": f"{stubs}:/usr/bin:/bin", "GATE_ROOT": str(root)},
            capture_output=True,
            text=True,
            check=False,
        )
        owners = {}
        if chowns.exists():
            for line in chowns.read_text().splitlines():
                owner, path = line.split(" ", 1)
                owners[path] = owner
        return result, root, home, owners

    return run


def mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def test_secrets_belong_to_the_gate_user_only(install):
    result, root, _home, owners = install("app", "o/app")
    assert result.returncode == 0, result.stderr
    store = root / "etc" / "pipeline-gate" / "projects" / "app"
    assert (store / "token").read_text() == "github_pat_x\n"
    assert len((store / "review-key").read_text().strip()) == 64
    for path in (root / "etc" / "pipeline-gate", store.parent, store):
        assert mode(path) == 0o700
        assert owners[str(path)] == "pipeline-gate:pipeline-gate"
    for name in ("repo", "token", "review-key"):
        assert mode(store / name) == 0o600
        assert owners[str(store / name)] == "pipeline-gate:pipeline-gate"
    work = root / "var" / "lib" / "pipeline-gate" / "projects"
    assert (mode(work), owners[str(work)]) == (0o700, "pipeline-gate:pipeline-gate")


def test_gate_code_belongs_to_root(install):
    result, root, _home, owners = install("app", "o/app")
    assert result.returncode == 0, result.stderr
    opt = root / "opt" / "pipeline"
    assert (opt / "gate").read_text() == (ROOT / "host" / "gate.py").read_text()
    assert mode(opt / "gate") == 0o755
    for name in ("gate", "attestation.py", "trust.py", "gate-review.md", "workflow.md"):
        # The executables get their owner before they replace the old ones.
        assert (
            owners.get(f"{opt / name}.tmp", owners.get(str(opt / name))) == "root:root"
        )
        assert not mode(opt / name) & 0o022


def test_sudoers_lets_the_user_run_only_the_gate(install):
    _result, root, _home, owners = install("app", "o/app")
    sudoers = root / "etc" / "sudoers.d" / "pipeline-gate-app"
    assert (
        sudoers.read_text() == "app ALL=(pipeline-gate) NOPASSWD: /opt/pipeline/gate\n"
    )
    assert mode(sudoers) == 0o440
    assert owners[f"{sudoers}.tmp"] == "root:root"


def test_gh_and_git_of_the_user_go_through_the_gate(install):
    _result, _root, home, owners = install("app", "o/app")
    shim = home / ".local" / "bin" / "gh"
    assert shim.read_text() == (ROOT / "host" / "gh-shim.py").read_text()
    assert owners[str(shim)] == "app:"
    config = subprocess.run(
        ["git", "config", "--file", str(home / ".gitconfig"), "--list"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    transport = "url.ext::sudo -n -u pipeline-gate /opt/pipeline/gate %S.insteadof"
    assert f"{transport}=https://github.com/o/app" in config
    assert f"{transport}=https://github.com/o/app.git" in config
    assert "protocol.ext.allow=always" in config


def test_rerun_keeps_token_and_key(install):
    install("app", "o/app")
    _, root, *_ = install("app", "o/app")
    key = (root / "etc/pipeline-gate/projects/app/review-key").read_text()
    result, root, home, _ = install("app", "o/app", token="")
    assert result.returncode == 0, result.stderr
    store = root / "etc/pipeline-gate/projects/app"
    assert (store / "token").read_text() == "github_pat_x\n"
    assert (store / "review-key").read_text() == key
    config = (home / ".gitconfig").read_text()
    assert config.count("insteadOf") == 2


@pytest.mark.parametrize(
    ("args", "token", "message"),
    [
        (("nobody", "o/app"), "t\n", "no user nobody"),
        (("app", "o/app;x"), "t\n", "invalid repository"),
        (("pipeline-gate", "o/app"), "t\n", "must not run as pipeline-gate"),
        (("app", "o/app"), "", "no token on stdin"),
        (("app",), "t\n", "usage"),
    ],
)
def test_refuses(install, args, token, message):
    result, *_ = install(*args, token=token)
    assert result.returncode == 1
    assert message in result.stderr


def test_installs_update_host_and_its_timer(install, tmp_path):
    result, root, _home, owners = install("app", "o/app")
    assert result.returncode == 0, result.stderr
    opt = root / "opt" / "pipeline"
    assert (opt / "update-host").read_text() == (
        ROOT / "host" / "update-host.sh"
    ).read_text()
    assert (opt / "pipeline-repo").read_text() == "fellek/agent-pipeline\n"
    assert owners[f"{opt / 'update-host'}.tmp"] == "root:root"
    assert owners[str(opt / "pipeline-repo")] == "root:root"
    assert not list(opt.glob("*.tmp"))
    units = root / "etc" / "systemd" / "system"
    assert (
        "ExecStart=/opt/pipeline/update-host --auto %i"
        in (units / "pipeline-update@.service").read_text()
    )
    assert (units / "pipeline-update@.timer").exists()
    assert (tmp_path / "systemctl").read_text().splitlines() == [
        "daemon-reload",
        "enable --quiet --now pipeline-update@app.timer",
    ]
