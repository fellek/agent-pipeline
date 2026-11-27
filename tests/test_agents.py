import pytest
from conftest import ROOT, frontmatter

AGENTS = sorted((ROOT / "agents").glob("*.md"))


@pytest.mark.parametrize("path", AGENTS, ids=lambda p: p.name)
def test_agents_fetch_pages_but_do_not_search_the_web(path):
    tools = frontmatter(path)["tools"].split(", ")
    assert "WebFetch" in tools
    assert "WebSearch" not in tools


@pytest.mark.parametrize("path", AGENTS, ids=lambda p: p.name)
def test_agents_treat_third_party_text_as_data(path):
    text = path.read_text()
    assert "data, not instructions" in text
    assert "OWNER, MEMBER or COLLABORATOR" in text
