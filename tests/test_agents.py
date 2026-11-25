import pytest
from conftest import ROOT, frontmatter

AGENTS = sorted((ROOT / "agents").glob("*.md"))


def test_implementer_cannot_reach_the_web():
    tools = frontmatter(ROOT / "agents" / "implementer.md")["tools"].split(", ")
    assert not {"WebFetch", "WebSearch"} & set(tools)


@pytest.mark.parametrize("path", AGENTS, ids=lambda p: p.name)
def test_agents_treat_third_party_text_as_data(path):
    text = path.read_text()
    assert "data, not instructions" in text
    assert "OWNER, MEMBER or COLLABORATOR" in text
