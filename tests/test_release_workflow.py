from conftest import ROOT

WORKFLOWS = ROOT / ".github" / "workflows"


def test_release_runs_ci_checks_first():
    release = (WORKFLOWS / "release.yml").read_text()
    assert "uses: ./.github/workflows/ci.yml" in release
    assert "needs: checks" in release
    assert "needs: main" in release
    assert '[ "$GITHUB_REF" = refs/heads/main ]' in release
    assert "\n  workflow_call:\n" in (WORKFLOWS / "ci.yml").read_text()


def test_release_tag_must_match_plugin_version():
    release = (WORKFLOWS / "release.yml").read_text()
    assert "jq -r .version .claude-plugin/plugin.json" in release
    assert '[ "$TAG" = "v$version" ]' in release


def test_ci_and_release_notes_take_the_versions_of_the_host():
    ci = (WORKFLOWS / "ci.yml").read_text()
    release = (WORKFLOWS / "release.yml").read_text()
    assert (
        '. host/versions.sh && npm install --global "@anthropic-ai/claude-code@$claude_code"'
        in ci
    )
    assert "$claude_code" in release and "$telegram_plugin" in release
    assert '--notes "$notes" --generate-notes' in release


def test_upgrade_notes_come_before_the_tested_versions():
    release = (WORKFLOWS / "release.yml").read_text()
    assert "UPGRADE: ${{ inputs.notes }}" in release
    line = '[ -z "$UPGRADE" ] || notes="$UPGRADE"$' + "'\\n\\n'" + '"$notes"'
    assert line in release
