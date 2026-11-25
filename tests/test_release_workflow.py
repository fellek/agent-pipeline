from conftest import ROOT

WORKFLOWS = ROOT / ".github" / "workflows"


def test_release_runs_ci_checks_first():
    release = (WORKFLOWS / "release.yml").read_text()
    assert "uses: ./.github/workflows/ci.yml" in release
    assert "needs: checks" in release
    assert "\n  workflow_call:\n" in (WORKFLOWS / "ci.yml").read_text()


def test_release_tag_must_match_plugin_version():
    release = (WORKFLOWS / "release.yml").read_text()
    assert "jq -r .version .claude-plugin/plugin.json" in release
    assert '[ "$TAG" = "v$version" ]' in release
