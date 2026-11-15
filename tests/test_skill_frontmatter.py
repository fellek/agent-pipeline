from pathlib import Path

import pytest

CLAUDE = Path(__file__).parents[1] / ".claude"


def frontmatter(path):
    lines = path.read_text().split("---\n")[1].splitlines()
    return dict(line.split(": ", 1) for line in lines)


FORKS_AND_COMMANDS = [
    path
    for path in sorted(CLAUDE.glob("skills/*/SKILL.md"))
    if frontmatter(path).get("context") == "fork"
] + sorted(CLAUDE.glob("commands/*.md"))


@pytest.mark.parametrize(
    "path", FORKS_AND_COMMANDS, ids=lambda p: str(p.relative_to(CLAUDE))
)
def test_declares_model_and_effort(path):
    assert {"model", "effort"} <= frontmatter(path).keys()


@pytest.mark.parametrize("skill", ["plan-issue", "issue", "review-issue", "fix-review"])
def test_step_skills_run_in_background(skill):
    assert frontmatter(CLAUDE / "skills" / skill / "SKILL.md")["background"] == "true"


@pytest.mark.parametrize("skill", ["issue", "review-issue", "fix-review"])
def test_step_skills_create_followup_issues(skill):
    assert "followup" in (CLAUDE / "skills" / skill / "SKILL.md").read_text()
