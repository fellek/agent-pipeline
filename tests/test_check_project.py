import json
import os
import re
import shutil
import subprocess
from fnmatch import fnmatch

import pytest
from conftest import ROOT, script_path

SCRIPT = script_path("check-project.py")
TEMPLATES = ROOT / "templates"
DENY = json.loads((TEMPLATES / "claude" / "settings.json").read_text())["permissions"][
    "deny"
]
REVIEW_WORKFLOWS = sorted(
    (TEMPLATES / "github" / "workflows").glob("agent-review*.yml")
)
RULES_IMPORT = "@.claude/skills/pipeline/rules/workflow.md"
MISSING_IMPORT = f"CLAUDE.md and .claude/CLAUDE.md lack an import of {RULES_IMPORT[1:]}"


@pytest.fixture
def app(tmp_path):
    """A project set up from the templates."""
    (tmp_path / ".claude").mkdir()
    shutil.copy(TEMPLATES / "claude" / "settings.json", tmp_path / ".claude")
    shutil.copy(TEMPLATES / "CLAUDE.md", tmp_path)
    shutil.copytree(TEMPLATES / "claude" / "rules", tmp_path / ".claude" / "rules")
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("name: CI\non: push\n")
    for template in REVIEW_WORKFLOWS:
        shutil.copy(template, tmp_path / ".github" / "workflows")
    return tmp_path


def check(cwd, *args):
    return subprocess.run(
        [str(SCRIPT), *args], cwd=cwd, check=False, capture_output=True, text=True
    )


def write_permissions(app, **rules):
    settings = app / ".claude" / "settings.json"
    data = json.loads(settings.read_text())
    data["permissions"].update(rules)
    settings.write_text(json.dumps(data))


def write_deny(app, rules):
    write_permissions(app, deny=rules)


def write_checks(app, commands, allow=()):
    (app / ".claude" / "rules" / "project.md").write_text(
        "## Checks\n\n<!-- note -->\n\n```\n"
        + "\n".join(commands)
        + "\n```\n\nRequired workflows: CI\n"
    )
    write_permissions(app, allow=list(allow))


def test_accepts_templates(app):
    result = check(app)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def web_fetch_rules(settings):
    return [r for r in settings["permissions"]["allow"] if r.startswith("WebFetch")]


def test_template_allows_web_fetch_only_for_exact_hosts(app):
    rules = web_fetch_rules(
        json.loads((TEMPLATES / "claude" / "settings.json").read_text())
    )
    assert rules
    assert all(re.fullmatch(r"WebFetch\(domain:[a-z0-9.-]+\)", r) for r in rules)


def test_pipeline_settings_allow_the_hosts_of_the_template():
    template = json.loads((TEMPLATES / "claude" / "settings.json").read_text())
    own = json.loads((ROOT / ".claude" / "settings.json").read_text())
    assert set(web_fetch_rules(template)) <= set(web_fetch_rules(own))


def test_accepts_extra_web_fetch_rules_and_domains(app):
    settings = app / ".claude" / "settings.json"
    data = json.loads(settings.read_text())
    data["permissions"]["allow"].append("WebFetch(domain:docs.example.org)")
    data["sandbox"]["network"]["allowedDomains"].append("registry.example.org")
    settings.write_text(json.dumps(data))
    result = check(app)
    assert (result.returncode, result.stderr) == (0, "")


def test_accepts_extra_deny_rules(app):
    write_deny(app, [*DENY, "Bash(rm -rf *)"])
    assert check(app).returncode == 0


@pytest.mark.parametrize("rule", DENY)
def test_fails_without_a_required_deny_rule(app, rule):
    write_deny(app, [r for r in DENY if r != rule])

    result = check(app)

    assert result.returncode == 1
    assert result.stderr.strip() == f".claude/settings.json lacks the deny rule {rule}"


def test_fails_without_session_start_hook(app):
    settings = app / ".claude" / "settings.json"
    data = json.loads(settings.read_text())
    del data["hooks"]
    settings.write_text(json.dumps(data))

    result = check(app)

    assert result.returncode == 1
    assert "lacks the SessionStart hook of the pipeline" in result.stderr
    assert "check-release.sh" in result.stderr


def test_accepts_extra_session_start_hooks(app):
    settings = app / ".claude" / "settings.json"
    data = json.loads(settings.read_text())
    data["hooks"]["SessionStart"].insert(
        0, {"hooks": [{"type": "command", "command": "true"}]}
    )
    settings.write_text(json.dumps(data))
    assert check(app).returncode == 0


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
    assert MISSING_IMPORT in result.stderr


@pytest.mark.parametrize(
    ("path", "line"),
    [
        (".claude/CLAUDE.md", "@skills/pipeline/rules/workflow.md"),
        (".claude/CLAUDE.md", "@./skills/pipeline/rules/../rules/workflow.md"),
        ("CLAUDE.md", "@./.claude/skills/pipeline/rules/workflow.md"),
    ],
)
def test_accepts_any_import_of_the_release_rules(app, path, line):
    (app / "CLAUDE.md").unlink()
    (app / path).write_text(f"# App\n\n{line}\n")

    assert check(app).returncode == 0


def test_accepts_import_by_absolute_path(app):
    (app / "CLAUDE.md").write_text(
        f"@{app}/.claude/skills/pipeline/rules/workflow.md\n"
    )

    assert check(app).returncode == 0


@pytest.mark.parametrize(
    ("path", "line"),
    [
        (".claude/CLAUDE.md", "@../rules/workflow.md"),
        (".claude/CLAUDE.md", RULES_IMPORT),
        ("CLAUDE.md", "@skills/pipeline/rules/workflow.md"),
    ],
)
def test_fails_for_an_import_of_other_rules(app, path, line):
    (app / "CLAUDE.md").unlink()
    (app / path).write_text(f"{line}\n")

    result = check(app)

    assert result.returncode == 1
    assert MISSING_IMPORT in result.stderr


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
        if not os.access(script, os.X_OK):
            continue
        assert f"Bash({script.name}*)" in allow, script.name


def test_template_rules_avoid_legacy_prefix_syntax():
    # Claude Code reads a trailing :* as a prefix of the text before it, so
    # Bash(git push * :*) would only match commands that start with "git push * ".
    permissions = json.loads((TEMPLATES / "claude" / "settings.json").read_text())[
        "permissions"
    ]
    for rule in permissions["allow"] + permissions["deny"]:
        assert not rule.endswith(":*)"), rule


def test_template_lets_the_autopilot_read_only_the_telegram_access_list():
    # The orchestrator reads the chat_id from access.json; .env holds the bot token.
    permissions = json.loads((TEMPLATES / "claude" / "settings.json").read_text())[
        "permissions"
    ]
    denied = [r[5:-1] for r in permissions["deny"] if r.startswith("Read(")]
    channel = "~/.claude/channels/telegram"
    assert f"Read({channel}/access.json)" in permissions["allow"]
    assert not any(fnmatch(f"{channel}/access.json", rule) for rule in denied)
    assert any(fnmatch(f"{channel}/.env", rule) for rule in denied)


@pytest.mark.parametrize(
    ("command", "rule"),
    [
        ("uv run pytest -q", "Bash(uv run *)"),
        ("uv run", "Bash(uv run *)"),
        ("uv run pytest", "Bash(uv run:*)"),
        ("uv run --frozen pytest", "Bash(uv run * pytest)"),
        ("npm test", "Bash(npm test)"),
        ("npm test", "Bash"),
        ("npm test", "Bash(*)"),
        ("make lint && make test", "Bash(make *)"),
        ("make test 2>&1", "Bash(make test *)"),
        ("make test &> log", "Bash(make test *)"),
        ("make test >&2", "Bash(make test *)"),
        ("pytest -k 'a|b'", "Bash(pytest *)"),
        ('pytest -k "a && b"', "Bash(pytest *)"),
    ],
)
def test_accepts_allowed_check_command(app, command, rule):
    write_checks(app, [command], allow=[rule])

    result = check(app)

    assert (result.returncode, result.stderr) == (0, "")


@pytest.mark.parametrize(
    ("command", "rule"),
    [
        ("uv runx", "Bash(uv run *)"),
        ("npm test --watch", "Bash(npm test)"),
        ("npm --help", "Bash(* --help *)"),
        ("make lint && npm test", "Bash(make *)"),
        ("make lint | tee log", "Bash(make *)"),
        ("make lint & npm test", "Bash(make *)"),
        ("make lint |& npm test", "Bash(make *)"),
        ("make lint; npm test", "Bash(make *)"),
        ("npm test", "Read(./npm test)"),
    ],
)
def test_fails_for_check_command_without_allow_rule(app, command, rule):
    write_checks(app, ["make lint", command], allow=["Bash(make lint)", rule])

    result = check(app)

    assert result.returncode == 1
    assert result.stderr.strip() == (
        f".claude/settings.json does not allow the check command {command}"
    )


def test_fails_for_check_command_that_a_deny_rule_matches(app):
    command = "git clean -n && uv run pytest"
    write_checks(app, [command], allow=["Bash"])

    result = check(app)

    assert result.returncode == 1
    assert result.stderr.strip() == (
        f".claude/settings.json denies the check command {command}"
    )


def test_reads_only_the_checks_block(app):
    (app / ".claude" / "rules" / "project.md").write_text(
        "## Build\n\n```\nmake build\n```\n\n## Checks\n\n```\nnpm test\n```\n"
        "\nRequired workflows: CI\n"
        "\n## Other\n\n```\nmake other\n```\n"
    )

    result = check(app)

    assert result.stderr.strip() == (
        ".claude/settings.json does not allow the check command npm test"
    )


@pytest.mark.parametrize(
    "project_md",
    [None, "# Rules\n", "## Checks\n\nNone yet.\n\n## Other\n\n```\nx\n```\n"],
)
def test_accepts_missing_checks(app, project_md):
    path = app / ".claude" / "rules" / "project.md"
    if project_md is None:
        path.unlink()
    else:
        path.write_text(project_md)

    assert check(app).returncode == 0


SANDBOX_SWITCHES = {
    key: value
    for key, value in json.loads((TEMPLATES / "claude" / "settings.json").read_text())[
        "sandbox"
    ].items()
    if isinstance(value, bool)
}


def test_template_enables_the_sandbox_without_escape():
    assert SANDBOX_SWITCHES == {
        "enabled": True,
        "failIfUnavailable": True,
        "autoAllowBashIfSandboxed": False,
        "allowUnsandboxedCommands": False,
    }


@pytest.mark.parametrize("key", SANDBOX_SWITCHES)
def test_fails_for_a_changed_sandbox_switch(app, key):
    settings = app / ".claude" / "settings.json"
    data = json.loads(settings.read_text())
    data["sandbox"][key] = not data["sandbox"][key]
    settings.write_text(json.dumps(data))

    result = check(app)

    assert result.returncode == 1
    expected = json.dumps(SANDBOX_SWITCHES[key])
    assert (
        result.stderr.strip()
        == f".claude/settings.json lacks sandbox.{key}: {expected}"
    )


def test_fails_without_sandbox(app):
    settings = app / ".claude" / "settings.json"
    data = json.loads(settings.read_text())
    del data["sandbox"]
    settings.write_text(json.dumps(data))

    lines = check(app).stderr.strip().splitlines()
    assert len(lines) == len(SANDBOX_SWITCHES) + len(DENIED_READS)


def test_template_runs_the_pipeline_commands_outside_the_sandbox():
    settings = json.loads((TEMPLATES / "claude" / "settings.json").read_text())
    allow = [r[5:-1] for r in settings["permissions"]["allow"] if r.startswith("Bash(")]
    excluded = settings["sandbox"]["excludedCommands"]
    # Writing a text for gh needs a heredoc, which keeps the call in the sandbox.
    assert set(allow) - {"cat > .pipeline/*"} <= set(excluded)
    # gh goes through sudo to the gate, which fails inside the sandbox.
    assert "gh *" in excluded


@pytest.mark.parametrize(
    ("line", "problem"),
    [
        ("", ".claude/rules/project.md lacks a line Required workflows: <name>, ..."),
        (
            "Required workflows: CI, Integration",
            ".claude/rules/project.md requires the workflow Integration, which "
            + ".github/workflows lacks",
        ),
    ],
)
def test_checks_the_required_workflows(app, line, problem):
    (app / ".claude" / "rules" / "project.md").write_text(
        "## Checks\n\n```\n.claude/skills/pipeline/bin/check-project.py\n```\n\n"
        + line
        + "\n"
    )
    assert check(app).stderr.strip() == problem


def test_accepts_quoted_workflow_names(app):
    (app / ".github" / "workflows" / "ci.yml").write_text("name: 'CI'\n")
    assert check(app).returncode == 0


DENIED_READS = json.loads((TEMPLATES / "claude" / "settings.json").read_text())[
    "sandbox"
]["filesystem"]["denyRead"]


def test_template_keeps_the_credentials_from_sandboxed_commands():
    settings = json.loads((TEMPLATES / "claude" / "settings.json").read_text())
    assert set(DENIED_READS) == {
        "~/.config/gh",
        "~/.ssh",
        "~/.claude/.credentials.json",
        "~/.claude/channels",
    }
    assert {
        "Read(~/.config/gh/**)",
        "Read(~/.ssh/**)",
        "Read(~/.claude/.credentials.json)",
        "Bash(gh auth*)",
    } <= set(settings["permissions"]["deny"])


@pytest.mark.parametrize("path", DENIED_READS)
def test_fails_without_a_denied_read(app, path):
    settings = app / ".claude" / "settings.json"
    data = json.loads(settings.read_text())
    data["sandbox"]["filesystem"]["denyRead"].remove(path)
    settings.write_text(json.dumps(data))

    result = check(app)

    assert result.returncode == 1
    assert result.stderr.strip() == (
        f".claude/settings.json lacks sandbox.filesystem.denyRead: {path}"
    )


@pytest.mark.parametrize("change", ["edit", "delete"])
@pytest.mark.parametrize("template", REVIEW_WORKFLOWS, ids=lambda p: p.name)
def test_fails_for_a_drifted_review_workflow(app, template, change):
    copy = app / ".github" / "workflows" / template.name
    if change == "edit":
        copy.write_text(copy.read_text() + "# local\n")
    else:
        copy.unlink()

    result = check(app)

    assert result.returncode == 1
    assert result.stderr.strip() == (
        f".github/workflows/{template.name} differs from the template of the "
        f"pipeline release, copy {template}"
    )


def test_pipeline_repository_keeps_its_own_review_workflows():
    assert check(ROOT).returncode == 0
