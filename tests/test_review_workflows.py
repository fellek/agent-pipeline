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
