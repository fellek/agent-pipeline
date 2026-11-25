import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
TELEGRAM_MESSAGE_LIMIT = 4096
COMMANDS = [
    "help",
    "status",
    "pause",
    "weiter",
    "cleanup",
    "park #<n>",
    "stop #<n>",
    "/verbose",
    "label <name>",
    "update",
    "#<n> <text>",
    "/<task> <n>",
    "plan-issue",
    "issue",
    "review-issue",
    "fix-review",
]
HEADING = "## Telegram-Befehle"


def command_section():
    text = (ROOT / "docs" / "autopilot.md").read_text()
    return re.search(
        rf"^{HEADING}\n(.*?)(?=^## |\Z)", text, re.DOTALL | re.MULTILINE
    ).group(0)


def test_command_section_lists_every_command():
    section = command_section()
    for command in COMMANDS:
        assert f"`{command}`" in section


def test_command_section_fits_one_telegram_message():
    assert len(command_section()) < TELEGRAM_MESSAGE_LIMIT


def test_orchestrator_answers_help_from_command_section():
    skill = (ROOT / "skills" / "autopilot" / "SKILL.md").read_text()
    assert f"`help` replies with the section `{HEADING}`" in skill
    assert skill.count("`help`") >= 3


def test_install_names_every_prerequisite_of_start_script():
    start = (ROOT / "host" / "autopilot-start.sh").read_text()
    install = (ROOT / "INSTALL.md").read_text()
    commands = re.search(r"^for cmd in (.+); do$", start, re.MULTILINE).group(1)
    min_claude = re.search(r"^min_claude=(\S+)$", start, re.MULTILINE).group(1)
    for command in [*commands.split(), "python3"]:
        assert f"`{command}`" in install
    assert f"`claude` (mindestens {min_claude})" in install


def test_pipeline_finding_reaches_maintainer():
    rules = (ROOT / "rules" / "workflow.md").read_text()
    skill = (ROOT / "skills" / "autopilot" / "SKILL.md").read_text()
    result_block = rules.split("```")[1]
    assert "\nPIPELINE_FINDING: <comment url>" in result_block
    assert "`PIPELINE_FINDING` line" in rules
    assert (
        "`PIPELINE_FINDING: <comment url>` line, send "
        "`#<n> Pipeline-Befund: <comment url>`" in skill
    )


def test_orchestrator_restarts_on_new_pinned_release():
    skill = (ROOT / "skills" / "autopilot" / "SKILL.md").read_text()
    merge = skill.split("\n## Merge\n")[1].split("\n## ")[0]
    restart = skill.split("\n## Restart\n")[1].split("\n## ")[0]
    assert "just invoked, run `release-changed.sh record`" in skill
    assert "run `release-changed.sh`" in merge
    assert "Restart with" in merge
    assert "infrastructure" not in merge
    assert "`.claude/pipeline-release` exists" in restart
    assert "`.claude/skills/pipeline/host/use-release.sh`" in restart
    assert "`autopilot-restart.sh`" in restart


def test_update_command_runs_routine():
    skill = (ROOT / "skills" / "autopilot" / "SKILL.md").read_text()
    update = next(line for line in skill.splitlines() if line.startswith("- `update`"))
    assert "`release-changed.sh`" in update
    assert "`.claude/skills/pipeline/host/update-pipeline.sh`" in update
    assert "Restart with" in update
