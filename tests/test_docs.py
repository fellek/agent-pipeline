import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
DOCS = sorted(
    path
    for pattern in (
        "*.md",
        ".claude/*.md",
        "docs/**/*.md",
        "rules/*.md",
        "skills/*/SKILL.md",
    )
    for path in ROOT.glob(pattern)
)
LINK = re.compile(r"\]\(([^)\s]+)\)")


def doc_id(path):
    return str(path.relative_to(ROOT))


def anchors(path):
    text = re.sub(r"^```.*?^```", "", path.read_text(), flags=re.DOTALL | re.MULTILINE)
    headings = re.findall(r"^#+ (.+)$", text, re.MULTILINE)
    return {re.sub(r"[^\w\- ]", "", h.lower()).replace(" ", "-") for h in headings}


@pytest.mark.parametrize("path", DOCS, ids=doc_id)
def test_relative_links_resolve(path):
    for link in LINK.findall(path.read_text()):
        if re.match(r"[a-z]+:", link):
            continue
        target, _, anchor = link.partition("#")
        file = (path.parent / target).resolve() if target else path
        assert file.exists(), link
        if anchor:
            assert anchor in anchors(file), link


def test_anchors_follow_github_slugs(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Title\n\n## Posting images in GitHub issues\n## Fehlersuche\n")
    assert anchors(doc) == {"title", "posting-images-in-github-issues", "fehlersuche"}


def test_claude_md_imports_workflow_rules():
    claude_md = ROOT / ".claude" / "CLAUDE.md"
    imports = re.findall(r"^@(\S+)$", claude_md.read_text(), re.MULTILINE)
    assert [(claude_md.parent / path).resolve() for path in imports] == [
        ROOT / ".claude" / "skills" / "pipeline" / "rules" / "workflow.md"
    ]


def test_workflow_rules_name_no_project():
    text = (ROOT / "rules" / "workflow.md").read_text()
    assert "master" not in text
    assert re.findall(r"github\.com/([^/\s`]+)", text) == ["<owner>"]
