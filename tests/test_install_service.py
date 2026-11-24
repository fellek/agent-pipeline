import subprocess

import pytest
from conftest import copy_scripts, project, write_executable


def unit_settings(path):
    return dict(
        line.split("=", 1) for line in path.read_text().splitlines() if "=" in line
    )


@pytest.fixture
def install(tmp_path):
    host = tmp_path / "plugin" / "host"
    copy_scripts(
        host,
        "install-service.sh",
        "autopilot-name.sh",
        "autopilot.service",
        "require-project-root.sh",
    )
    stubs = tmp_path / "bin"
    stubs.mkdir()
    calls = tmp_path / "systemctl_calls"
    write_executable(stubs / "systemctl", f'echo "$*" >> {calls}')
    tmux_calls = tmp_path / "tmux_calls"
    write_executable(stubs / "tmux", f'echo "$*" >> {tmux_calls}')

    class Install:
        host_dir = host

        @staticmethod
        def calls():
            return calls.read_text().splitlines() if calls.exists() else []

        @staticmethod
        def tmux_calls():
            return tmux_calls.read_text().splitlines() if tmux_calls.exists() else []

        @staticmethod
        def units(user="alice"):
            return tmp_path / user / "config" / "systemd" / "user"

        @staticmethod
        def run(cwd, *args, user="alice"):
            config = tmp_path / user / "config"
            result = subprocess.run(
                [str(host / "install-service.sh"), *args],
                cwd=cwd,
                env={
                    "PATH": f"{stubs}:/usr/bin:/bin",
                    "HOME": str(tmp_path / user),
                    "XDG_CONFIG_HOME": str(config),
                    "XDG_RUNTIME_DIR": str(tmp_path),
                },
                check=False,
                capture_output=True,
                text=True,
            )
            return result, config / "systemd" / "user"

    return Install()


def test_unit_runs_project_with_plugin_scripts(install, app):
    result, units = install.run(app)
    assert result.returncode == 0, result.stderr
    unit = units / "autopilot-app.service"
    assert "@" not in unit.read_text()
    settings = unit_settings(unit)
    assert settings["WorkingDirectory"] == str(app)
    assert settings["ExecStart"] == f"{install.host_dir}/autopilot-service.sh ready"
    assert settings["ExecStop"] == f"{install.host_dir}/autopilot-stop.sh"
    assert install.calls()[-1] == "--user enable --now autopilot-app.service"


def test_unit_starts_service_with_label(install, app):
    _, units = install.run(app, "batch-1")
    unit = unit_settings(units / "autopilot-app.service")
    assert unit["ExecStart"].endswith("/autopilot-service.sh batch-1")


@pytest.mark.parametrize("args", [("batch 1",), ("batch", "1"), ("a|b",), ("a%b",)])
def test_rejects_invalid_label(install, app, args):
    result, units = install.run(app, *args)
    assert result.returncode == 1
    assert not units.exists()


def test_rejects_project_path_with_special_characters(install, tmp_path):
    result, units = install.run(project(tmp_path / "my app", "https://x/o/app"))
    assert result.returncode == 1
    assert "unsupported path" in result.stderr
    assert not units.exists()


def test_two_instances_for_different_users(install, tmp_path):
    first = project(tmp_path / "alice" / "app", "git@github.com:o/app.git")
    second = project(tmp_path / "bob" / "site", "git@github.com:o/site.git")

    _, alice_units = install.run(first, user="alice")
    _, bob_units = install.run(second, user="bob")

    assert [p.name for p in alice_units.iterdir()] == ["autopilot-app.service"]
    assert [p.name for p in bob_units.iterdir()] == ["autopilot-site.service"]
    assert unit_settings(alice_units / "autopilot-app.service")[
        "WorkingDirectory"
    ] == str(first)
    assert unit_settings(bob_units / "autopilot-site.service")[
        "WorkingDirectory"
    ] == str(second)


def test_rejects_subdirectory_of_project(install, app):
    (app / "docs").mkdir()
    result, units = install.run(app / "docs")
    assert result.returncode == 1
    assert "project root" in result.stderr
    assert not units.exists()


def old_unit(install, project):
    """The unit of versions with one instance per host, %h relative to the home."""
    units = install.units()
    units.mkdir(parents=True)
    unit = units / "autopilot.service"
    unit.write_text(f"[Service]\nWorkingDirectory={project}\n")
    return unit


def test_replaces_old_unit_and_session_of_project(install, tmp_path):
    app = project(tmp_path / "alice" / "app", "git@github.com:o/app.git")
    unit = old_unit(install, "%h/app")

    result, units = install.run(app)

    assert result.returncode == 0, result.stderr
    assert not unit.exists()
    assert [p.name for p in units.iterdir()] == ["autopilot-app.service"]
    assert install.calls()[0] == "--user disable --now autopilot.service"
    assert install.tmux_calls() == ["kill-session -t =autopilot"]
    assert "replaced autopilot.service" in result.stdout


def test_keeps_old_unit_of_other_project(install, app):
    unit = old_unit(install, "%h/other")

    result, units = install.run(app)

    assert result.returncode == 1
    assert "remove it first" in result.stderr
    assert unit.exists()
    assert [p.name for p in units.iterdir()] == ["autopilot.service"]
    assert install.calls() == []
    assert install.tmux_calls() == []
