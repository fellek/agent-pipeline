#!/usr/bin/env python3
"""Check the rules GitHub applies to the default branch of the project.

Required: a pull request, the status checks `agent-review` and at least one
other check, and blocked force pushes. GitHub returns no rules for a private
repository without a plan that enforces rulesets, so there no rules at all only
warns: the gate of the host is the protection there.

Prints the missing rules. Exits 1 if a rule is missing, unless the repository is
private and has no rules.

Usage:
  check-ruleset.py <branch>
"""

import json
import subprocess
import sys
from urllib.parse import quote

REVIEW_CHECK = "agent-review"


def gh_api(path):
    return json.loads(
        subprocess.run(
            ["gh", "api", path], capture_output=True, text=True, check=True
        ).stdout
    )


def missing_rules(rules):
    types = {rule["type"] for rule in rules}
    contexts = {
        check["context"]
        for rule in rules
        if rule["type"] == "required_status_checks"
        for check in rule["parameters"]["required_status_checks"]
    }
    missing = [
        name
        for name, present in (
            ("pull_request", "pull_request" in types),
            (f"required_status_checks with {REVIEW_CHECK}", REVIEW_CHECK in contexts),
            ("required_status_checks with the CI", bool(contexts - {REVIEW_CHECK})),
            ("non_fast_forward", "non_fast_forward" in types),
        )
        if not present
    ]
    return missing


def main(argv):
    match argv:
        case [branch]:
            pass
        case _:
            sys.exit(__doc__)
    try:
        private = gh_api("repos/{owner}/{repo}")["private"]
        rules = gh_api(
            f"repos/{{owner}}/{{repo}}/rules/branches/{quote(branch, safe='')}"
            "?per_page=100"
        )
    except subprocess.CalledProcessError as error:
        sys.exit(f"reading the rules failed: {error.stderr.strip()}")
    missing = missing_rules(rules)
    if not missing:
        return
    message = f"the default branch {branch} lacks the rules: {', '.join(missing)}"
    if private and not rules:
        print(f"Warning: {message}. GitHub enforces no ruleset here without a plan.")
        return
    sys.exit(message)


if __name__ == "__main__":
    main(sys.argv[1:])
