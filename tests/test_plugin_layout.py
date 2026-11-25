import json
import re
from pathlib import Path

import pytest
from conftest import frontmatter

ROOT = Path(__file__).parents[1]
PLUGIN = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["name"]
SKILLS = sorted(ROOT.glob("skills/*/SKILL.md"))
AGENT_SKILLS = [path for path in SKILLS if "agent" in frontmatter(path)]


def skill_id(path):
    return path.parent.name


@pytest.mark.parametrize("path", AGENT_SKILLS, ids=skill_id)
def test_skill_agent_is_an_agent_of_this_plugin(path):
    prefix, _, name = frontmatter(path)["agent"].partition(":")
    assert prefix == PLUGIN
    assert frontmatter(ROOT / "agents" / f"{name}.md")["name"] == name


def test_orchestrator_names_existing_skills():
    text = (ROOT / "skills" / "autopilot" / "SKILL.md").read_text()
    names = set(re.findall(rf"`{PLUGIN}:([a-z-]+)`", text))
    assert names
    assert {skill_id(path) for path in SKILLS} >= names


@pytest.mark.parametrize("path", SKILLS, ids=skill_id)
def test_skill_scripts_are_plugin_commands(path):
    scripts = set(re.findall(r"`([a-z-]+\.(?:py|sh))\b", path.read_text()))
    assert {script.name for script in (ROOT / "bin").iterdir()} >= scripts


def test_hook_commands_exist():
    hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]
    commands = [
        hook["command"]
        for matchers in hooks.values()
        for matcher in matchers
        for hook in matcher["hooks"]
    ]
    assert commands
    for command in commands:
        path = ROOT / command.removeprefix('"${CLAUDE_PLUGIN_ROOT}"/')
        assert path.is_file()
        assert path.stat().st_mode & 0o111


WORKFLOW = "${CLAUDE_PLUGIN_ROOT}/rules/workflow.md"
STEP_SKILLS = [path for path in AGENT_SKILLS if skill_id(path) != "fork-check"]


@pytest.mark.parametrize(
    "path", SKILLS + sorted(ROOT.glob("agents/*.md")), ids=lambda p: p.stem
)
def test_no_pipeline_rule_from_claude_md(path):
    # A project's CLAUDE.md may lack the import of the pipeline rules.
    assert not re.search(r"(from|in|Follow) CLAUDE\.md", path.read_text())


@pytest.mark.parametrize("path", STEP_SKILLS, ids=skill_id)
def test_step_skill_names_workflow_rules_of_plugin(path):
    assert WORKFLOW in path.read_text()


def test_workflow_rules_hold_what_skills_refer_to():
    text = (ROOT / WORKFLOW.removeprefix("${CLAUDE_PLUGIN_ROOT}/")).read_text()
    assert "## Autopilot operation" in text
    assert "STATUS: done | blocked | needs_input" in text
