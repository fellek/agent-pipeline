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


def test_install_names_every_prerequisite_of_start_script():
    start = (ROOT / "host" / "autopilot-start.sh").read_text()
    install = (ROOT / "INSTALL.md").read_text()
    commands = re.search(r"^for cmd in (.+); do$", start, re.MULTILINE).group(1)
    for command in [*commands.split(), "python3"]:
        assert f"`{command}`" in install
    assert "`claude` in der Version aus [`host/versions.sh`]" in install


def test_pipeline_finding_reaches_maintainer():
    rules = (ROOT / "rules" / "workflow.md").read_text()
    result_block = rules.split("```")[1]
    assert "\nPIPELINE_FINDING: <comment url>" in result_block
    assert "`PIPELINE_FINDING` line" in rules
