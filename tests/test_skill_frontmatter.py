from pathlib import Path

import pytest
from conftest import frontmatter

ROOT = Path(__file__).parents[1]


# The autopilot runs in the session's own model; every other skill pins its own.
PINNED = [
    path
    for path in sorted(ROOT.glob("skills/*/SKILL.md"))
    if path.parent.name != "autopilot"
]


@pytest.mark.parametrize("path", PINNED, ids=lambda p: str(p.relative_to(ROOT)))
def test_declares_model_and_effort(path):
    assert {"model", "effort"} <= frontmatter(path).keys()


@pytest.mark.parametrize(
    "skill",
    ["plan-issue", "issue", "review-issue", "fix-review", "find-answer", "setprio"],
)
def test_step_skills_run_in_background(skill):
    assert frontmatter(ROOT / "skills" / skill / "SKILL.md")["background"] == "true"


@pytest.mark.parametrize("skill", ["issue", "review-issue", "fix-review"])
def test_step_skills_create_followup_issues(skill):
    assert "followup" in (ROOT / "skills" / skill / "SKILL.md").read_text()
