import pytest
from conftest import load_script

shim = load_script("gh-shim.py")


@pytest.mark.parametrize(
    ("args", "converted", "path"),
    [
        (
            ["pr", "create", "--head", "b", "--body-file", "p.md"],
            ["pr", "create", "--head", "b", "--body-file", "-"],
            "p.md",
        ),
        (
            ["issue", "comment", "5", "-F", "c.md"],
            ["issue", "comment", "5", "-F", "-"],
            "c.md",
        ),
        (
            ["issue", "comment", "5", "--body-file=c.md"],
            ["issue", "comment", "5", "--body-file", "-"],
            "c.md",
        ),
        (["api", "x", "--input", "b.json"], ["api", "x", "--input", "-"], "b.json"),
        (["api", "x", "-F", "a=1"], ["api", "x", "-F", "a=1"], None),
        (
            ["issue", "comment", "5", "--body-file", "-"],
            ["issue", "comment", "5", "--body-file", "-"],
            None,
        ),
        (
            ["issue", "comment", "5", "--body", "hi"],
            ["issue", "comment", "5", "--body", "hi"],
            None,
        ),
    ],
)
def test_a_file_flag_becomes_stdin(args, converted, path):
    assert shim.convert(args) == (converted, path)


def test_rejects_two_file_flags():
    with pytest.raises(SystemExit):
        shim.convert(["pr", "create", "-F", "a", "--input", "b"])


def test_runs_the_gate_with_the_file_on_stdin(tmp_path, monkeypatch):
    body = tmp_path / "b.md"
    body.write_text("text with `code` and $HOME\n")
    ran = {}

    def execvp(file, argv):
        ran["argv"] = argv
        with open(0, closefd=False) as stdin:
            ran["stdin"] = stdin.read()

    monkeypatch.setattr(shim.os, "execvp", execvp)
    saved = shim.os.dup(0)
    try:
        shim.main(["issue", "comment", "5", "--body-file", str(body)])
    finally:
        shim.os.dup2(saved, 0)
        shim.os.close(saved)
    assert ran["argv"] == [*shim.GATE, "issue", "comment", "5", "--body-file", "-"]
    assert ran["stdin"] == "text with `code` and $HOME\n"
