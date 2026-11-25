import json
import subprocess

import pytest
from conftest import load_script, run_main

COMPLETE = [
    {"type": "pull_request", "parameters": {}},
    {
        "type": "required_status_checks",
        "parameters": {
            "required_status_checks": [
                {"context": "checks"},
                {"context": "agent-review"},
            ]
        },
    },
    {"type": "non_fast_forward"},
]


@pytest.fixture
def ruleset():
    return load_script("check-ruleset.py")


def fake_gh(monkeypatch, private, rules):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if args[-1] == "repos/{owner}/{repo}":
            return subprocess.CompletedProcess(
                args, 0, json.dumps({"private": private})
            )
        return subprocess.CompletedProcess(args, 0, json.dumps(rules))

    monkeypatch.setattr(subprocess, "run", run)
    return calls


def test_complete_rules_pass_silently(monkeypatch, capsys, ruleset):
    calls = fake_gh(monkeypatch, False, COMPLETE)
    assert run_main(ruleset, capsys, "main") == ("", 0)
    assert calls[1] == ["gh", "api", "repos/{owner}/{repo}/rules/branches/main"]


def test_rules_from_several_rulesets_count_together(monkeypatch, capsys, ruleset):
    split = [
        *COMPLETE[:1],
        {
            "type": "required_status_checks",
            "parameters": {"required_status_checks": [{"context": "agent-review"}]},
        },
        {
            "type": "required_status_checks",
            "parameters": {"required_status_checks": [{"context": "CI"}]},
        },
        *COMPLETE[2:],
    ]
    fake_gh(monkeypatch, False, split)
    assert run_main(ruleset, capsys, "main") == ("", 0)


@pytest.mark.parametrize(
    ("rules", "missing"),
    [
        (
            [],
            (
                "pull_request, required_status_checks with agent-review, "
                "required_status_checks with the CI, non_fast_forward"
            ),
        ),
        ([r for r in COMPLETE if r["type"] != "pull_request"], "pull_request"),
        ([r for r in COMPLETE if r["type"] != "non_fast_forward"], "non_fast_forward"),
        (
            [
                *COMPLETE[:1],
                {
                    "type": "required_status_checks",
                    "parameters": {"required_status_checks": [{"context": "checks"}]},
                },
                *COMPLETE[2:],
            ],
            "required_status_checks with agent-review",
        ),
        (
            [
                *COMPLETE[:1],
                {
                    "type": "required_status_checks",
                    "parameters": {
                        "required_status_checks": [{"context": "agent-review"}]
                    },
                },
                *COMPLETE[2:],
            ],
            "required_status_checks with the CI",
        ),
    ],
)
def test_public_repository_fails_naming_the_missing_rules(
    monkeypatch, capsys, ruleset, rules, missing
):
    fake_gh(monkeypatch, False, rules)
    with pytest.raises(SystemExit) as error:
        ruleset.main(["main"])
    assert error.value.code == f"the default branch main lacks the rules: {missing}"


def test_private_repository_only_warns(monkeypatch, capsys, ruleset):
    fake_gh(monkeypatch, True, [])
    out, code = run_main(ruleset, capsys, "main")
    assert code == 0
    assert out.startswith("Warning: the default branch main lacks the rules: ")


def test_failing_gh_names_its_error(monkeypatch, ruleset):
    def run(args, **kwargs):
        raise subprocess.CalledProcessError(1, args, stderr="HTTP 404\n")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(SystemExit) as error:
        ruleset.main(["main"])
    assert error.value.code == "reading the rules failed: HTTP 404"


def test_branch_name_is_quoted(monkeypatch, capsys, ruleset):
    calls = fake_gh(monkeypatch, False, COMPLETE)
    run_main(ruleset, capsys, "release/1")
    assert calls[1][-1] == "repos/{owner}/{repo}/rules/branches/release%2F1"


def test_usage_without_branch(ruleset):
    with pytest.raises(SystemExit) as error:
        ruleset.main([])
    assert "Usage" in error.value.code
