import pytest
from conftest import exit_status, script_path


def test_script_path_names_missing_script():
    with pytest.raises(FileNotFoundError, match="no-such-script.py"):
        script_path("no-such-script.py")


def test_script_path_rejects_ambiguous_name(tmp_path, monkeypatch):
    for folder in ("bin", "host"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "twice.sh").touch()
    monkeypatch.setattr("conftest.ROOT", tmp_path)
    with pytest.raises(RuntimeError, match="ambiguous"):
        script_path("twice.sh")


@pytest.mark.parametrize(("code", "status"), [(None, 0), (0, 0), (2, 2), ("failed", 1)])
def test_exit_status_matches_interpreter(code, status):
    assert exit_status(code) == status
