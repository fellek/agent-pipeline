import re

import pytest
from conftest import ROOT

WORKFLOWS = [
    ROOT / folder / name
    for folder in (".github/workflows", "templates/github/workflows")
    for name in ("agent-review.yml", "agent-review-sync.yml")
]


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: str(p.relative_to(ROOT)))
def test_the_review_key_reaches_only_code_of_the_base(path):
    text = path.read_text()
    checkout = re.search(
        r"uses: actions/checkout@\S+.*?\n(?=      - )", text, re.DOTALL
    )
    assert "ref: ${{ github.event.pull_request.base.sha }}" in checkout.group(0)
    assert text.index("actions/checkout") < text.index("review-key:")


def pins(folder):
    found = {}
    for path in (ROOT / folder).glob("*.yml"):
        for action, ref in re.findall(r"uses: ([\w-]+/[\w-]+)@(\S+)", path.read_text()):
            found.setdefault(action, set()).add(ref)
    return found


def test_templates_pin_the_actions_of_this_repository():
    # Dependabot updates only .github/workflows; a bump PR stays red until the
    # templates follow.
    ours = pins(".github/workflows")
    for action, refs in pins("templates/github/workflows").items():
        assert refs == ours[action], action
