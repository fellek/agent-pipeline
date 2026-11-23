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
