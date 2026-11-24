import json
import shutil
import subprocess

import pytest
from conftest import ROOT, script_path

SCRIPT = script_path("check-project.py")
TEMPLATES = ROOT / "templates"
DENY = json.loads((TEMPLATES / "claude" / "settings.json").read_text())["permissions"][
    "deny"
]
RULES_IMPORT = "@.claude/skills/pipeline/rules/workflow.md"


@pytest.fixture
def app(tmp_path):
    """A project set up from the templates."""
    (tmp_path / ".claude").mkdir()
    shutil.copy(TEMPLATES / "claude" / "settings.json", tmp_path / ".claude")
    shutil.copy(TEMPLATES / "CLAUDE.md", tmp_path)
    return tmp_path


def check(cwd, *args):
    return subprocess.run(
        [str(SCRIPT), *args], cwd=cwd, check=False, capture_output=True, text=True
    )


def write_deny(app, rules):
    settings = app / ".claude" / "settings.json"
    data = json.loads(settings.read_text())
    data["permissions"]["deny"] = rules
    settings.write_text(json.dumps(data))


def test_accepts_templates(app):
    result = check(app)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_accepts_extra_deny_rules(app):
    write_deny(app, [*DENY, "Bash(rm -rf *)"])
    assert check(app).returncode == 0


@pytest.mark.parametrize("rule", DENY)
def test_fails_without_a_required_deny_rule(app, rule):
    write_deny(app, [r for r in DENY if r != rule])

    result = check(app)

    assert result.returncode == 1
    assert result.stderr.strip() == f".claude/settings.json lacks the deny rule {rule}"


def test_fails_without_settings(app):
    (app / ".claude" / "settings.json").unlink()

    result = check(app)

    assert result.returncode == 1
    assert ".claude/settings.json is missing" in result.stderr


def test_fails_for_invalid_settings(app):
    (app / ".claude" / "settings.json").write_text("{")

    result = check(app)

    assert result.returncode == 1
    assert "no valid JSON" in result.stderr


@pytest.mark.parametrize(
    "claude_md", ["# App\n", f"See {RULES_IMPORT} for the workflow.\n", None]
)
def test_fails_without_rules_import(app, claude_md):
    if claude_md is None:
        (app / "CLAUDE.md").unlink()
    else:
        (app / "CLAUDE.md").write_text(claude_md)

    result = check(app)

    assert result.returncode == 1
    assert f"CLAUDE.md lacks the line {RULES_IMPORT}" in result.stderr


def test_reports_all_problems(app):
    write_deny(app, [])
    (app / "CLAUDE.md").write_text("# App\n")

    lines = check(app).stderr.splitlines()

    assert len(lines) == len(DENY) + 1


def test_rejects_arguments(app):
    assert check(app, "x").returncode == 1


def test_template_allows_every_plugin_command():
    allow = json.loads((TEMPLATES / "claude" / "settings.json").read_text())[
        "permissions"
    ]["allow"]
    for script in (ROOT / "bin").glob("*.*"):
        assert f"Bash({script.name}*)" in allow, script.name


def test_template_rules_avoid_legacy_prefix_syntax():
    # Claude Code reads a trailing :* as a prefix of the text before it, so
    # Bash(git push * :*) would only match commands that start with "git push * ".
    permissions = json.loads((TEMPLATES / "claude" / "settings.json").read_text())[
        "permissions"
    ]
    for rule in permissions["allow"] + permissions["deny"]:
        assert not rule.endswith(":*)"), rule
