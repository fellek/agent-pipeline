import shutil
import subprocess

import pytest
from conftest import script_path, write_executable

UNIT = script_path("autopilot.service")


@pytest.fixture
def install(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".github" / "scripts").mkdir(parents=True)
    (repo / "deploy").mkdir()
    shutil.copy(script_path("install-service.sh"), repo / ".github" / "scripts")
    shutil.copy(UNIT, repo / "deploy")
    stubs = tmp_path / "bin"
    stubs.mkdir()
    write_executable(stubs / "systemctl", "exit 0")
    config = tmp_path / "config"

    def run(*args, check=True):
        result = subprocess.run(
            [str(repo / ".github" / "scripts" / "install-service.sh"), *args],
            env={
                "PATH": f"{stubs}:/usr/bin:/bin",
                "XDG_CONFIG_HOME": str(config),
                "XDG_RUNTIME_DIR": str(tmp_path),
            },
            check=check,
        )
        if not check:
            return result
        unit = (config / "systemd" / "user" / "autopilot.service").read_text()
        return next(line for line in unit.splitlines() if line.startswith("ExecStart"))

    return run


@pytest.mark.parametrize(("args", "label"), [((), "ready"), (("batch-1",), "batch-1")])
def test_unit_starts_service_with_label(install, args, label):
    assert install(*args).endswith(f"/autopilot-service.sh {label}")


@pytest.mark.parametrize("args", [("batch 1",), ("batch", "1"), ("a|b",), ("a%b",)])
def test_rejects_invalid_label(install, tmp_path, args):
    assert install(*args, check=False).returncode == 1
    assert not (tmp_path / "config" / "systemd" / "user" / "autopilot.service").exists()
