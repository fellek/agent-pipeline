import json
import os
import pwd
import subprocess
import sys

import attestation
import pytest
from conftest import ROOT, commit, git, load_script, script_path

GATE = script_path("gate.py")
SHA = "a" * 40
KEY = "k" * 64
TOKEN = "github_pat_secret"


@pytest.fixture
def gate(tmp_path, monkeypatch):
    module = load_script("gate.py")
    monkeypatch.setattr(module, "STORE", tmp_path / "store")
    monkeypatch.setattr(module, "WORK", tmp_path / "work")
    return module


def add_project(store, user, repo, token=TOKEN, key=KEY):
    folder = store / user
    folder.mkdir(parents=True)
    (folder / "repo").write_text(f"{repo}\n")
    (folder / "token").write_text(f"{token}\n")
    (folder / "review-key").write_text(f"{key}\n")


@pytest.fixture
def me():
    return pwd.getpwuid(os.getuid()).pw_name


@pytest.fixture
def project(gate, tmp_path, me, monkeypatch):
    add_project(tmp_path / "store", me, "o/app")
    monkeypatch.setenv("SUDO_UID", str(os.getuid()))
    return gate.Project(me)


# Selecting the project


def test_caller_selects_its_own_project(gate, tmp_path, me, monkeypatch):
    add_project(tmp_path / "store", me, "o/app", token="mine")
    add_project(tmp_path / "store", "other", "o/site", token="theirs")
    monkeypatch.setenv("SUDO_UID", str(os.getuid()))

    project = gate.project_of_caller()

    assert (project.repo, project.token) == ("o/app", "mine")
    assert project.env()["GH_REPO"] == "o/app"
    assert project.env()["GH_TOKEN"] == "mine"


def test_caller_without_project_is_refused(gate, monkeypatch):
    monkeypatch.setenv("SUDO_UID", str(os.getuid()))
    with pytest.raises(gate.Refused, match="no project for user"):
        gate.project_of_caller()


def test_gate_needs_sudo(gate, monkeypatch):
    monkeypatch.delenv("SUDO_UID", raising=False)
    with pytest.raises(gate.Refused, match="through sudo"):
        gate.project_of_caller()


def test_token_is_never_an_argument(project):
    env = project.env()
    assert TOKEN in env["GH_TOKEN"]
    assert "Basic" in env["GIT_CONFIG_VALUE_0"]


# gh


@pytest.mark.parametrize(
    "args",
    [
        ["issue", "view", "5", "--json", "body"],
        ["issue", "comment", "5", "--body", "x"],
        ["issue", "comment", "5", "--body-file", "-"],
        ["issue", "create", "--label", "followup", "--title", "t", "-F", "-"],
        ["pr", "create", "--head", "issue-5-x", "--body-file=-"],
        ["pr", "list", "--head", "issue-5-x", "-R", "O/App"],
        ["run", "watch", "7", "--exit-status"],
        ["release", "view", "v1", "--repo", "fellek/agent-pipeline"],
        ["api", "repos/{owner}/{repo}/pulls/5/reviews", "--paginate"],
        ["api", "repos/o/app/issues/5/comments", "-f", "body=x"],
        [
            "api",
            "-X",
            "PATCH",
            "repos/{owner}/{repo}/issues/comments/9",
            "-f",
            "body=x",
        ],
        [
            "api",
            "--method",
            "POST",
            "repos/o/app/pulls/5/comments/9/replies",
            "-f",
            "body=x",
        ],
        ["api", "graphql", "-F", "pr=5", "-f", "query=query { viewer { login } }"],
        ["api", "rate_limit", "--include"],
    ],
)
def test_allowed_gh_commands(gate, args):
    assert gate.gh_problem(args, "o/app") is None


@pytest.mark.parametrize(
    ("args", "problem"),
    [
        (["pr", "merge", "5", "--squash"], "gh pr merge is not allowed"),
        (["pr", "review", "5", "--approve"], "gh pr review is not allowed"),
        (["pr", "checkout", "5"], "gh pr checkout is not allowed"),
        (["auth", "token"], "gh auth token is not allowed"),
        (["repo", "delete", "o/app"], "gh repo delete is not allowed"),
        (["secret", "set", "X"], "gh secret set is not allowed"),
        (["issue", "delete", "5"], "gh issue delete is not allowed"),
        (["issue", "comment", "5", "--body-file", "/etc/x"], "--body-file reads only"),
        (["issue", "comment", "5", "-F", "/etc/x"], "-F reads only"),
        (["pr", "edit", "5", "--body-file=/etc/x"], "--body-file reads only"),
        (["pr", "list", "-R", "o/site"], "reaches only o/app"),
        (["issue", "list", "--repo=o/site"], "reaches only o/app"),
        (["api", "repos/o/site/issues"], "reaches only o/app"),
        (["api", "-X", "PUT", "repos/{owner}/{repo}/pulls/5/merge"], "PUT"),
        (["api", "repos/{owner}/{repo}/pulls/5/merge", "-X", "PUT"], "PUT"),
        (
            [
                "api",
                "-X",
                "PATCH",
                "repos/o/app/git/refs/heads/main",
                "-F",
                "force=true",
            ],
            "PATCH",
        ),
        (["api", "repos/o/app/git/refs", "-f", "ref=refs/heads/main"], "POST"),
        (["api", "repos/o/app/merges", "-f", "base=main"], "POST"),
        (["api", "--method=PUT", "repos/o/app/contents/a.py"], "PUT"),
        (["api", "repos/o/app/pulls/5/reviews", "-f", "event=APPROVE"], "POST"),
        (["api", "-X", "DELETE", "repos/o/app/issues/comments/9"], "DELETE"),
        (["api", "repos/o/app/issues/5/comments", "-F", "body=@/etc/x"], "file values"),
        (
            ["api", "repos/o/app/issues/5/comments", "--input", "/etc/x"],
            "--input reads",
        ),
        (["api", "--hostname", "evil.test", "user"], "--hostname"),
        (
            [
                "api",
                "graphql",
                "-f",
                "query=mutation { mergePullRequest(input: {}) { x } }",
            ],
            "only GraphQL queries",
        ),
        (["api", "graphql", "-F", "query=@-"], "file values"),
        (["api", "graphql"], "only GraphQL queries"),
        (["issue", "comment", "1", "-F/etc/x"], "-F needs its value"),
        (["pr", "list", "-Ro/site"], "-R needs its value"),
        (["pr", "create", "--recover", "/etc/x"], "--recover"),
        (["pr", "create", "--recover=/etc/x"], "--recover"),
        (["api", "-XPUT", "repos/o/app/pulls/1/merge"], "-X needs its value"),
        (["api", "repos/o/app/pulls/1/reviews", "-fevent=APPROVE"], "-f needs"),
        (["api", "repos/o/app/issues/5/comments", "-Ftitle=@/etc/x"], "-F needs"),
        (["api", "--unknown", "repos/o/app/issues"], "--unknown is not allowed"),
        ([], "needs a command"),
    ],
)
def test_refused_gh_commands(gate, args, problem):
    assert problem in gate.gh_problem(args, "o/app")


def test_gh_runs_with_the_token_of_the_project(gate, project, monkeypatch):
    calls = []
    monkeypatch.setattr(gate.os, "execvpe", lambda *a: calls.append(a))
    gate.run_gh(project, ["issue", "view", "5"])
    _file, argv, env = calls[0]
    assert argv == ["gh", "issue", "view", "5"]
    assert (env["GH_TOKEN"], env["GH_REPO"]) == (TOKEN, "o/app")


def test_refused_gh_does_not_run(gate, project, monkeypatch):
    monkeypatch.setattr(gate.os, "execvpe", lambda *a: pytest.fail("ran gh"))
    with pytest.raises(gate.Refused):
        gate.run_gh(project, ["pr", "merge", "5"])


# git push and fetch through the ext:: transport


@pytest.fixture
def transport(tmp_path, me, git_identity, monkeypatch):
    """A clone whose origin goes through the gate to a stand-in for GitHub."""
    github = tmp_path / "github" / "o" / "app.git"
    seed = tmp_path / "seed"
    git(tmp_path, "init", "-q", "-b", "main", str(seed))
    commit(seed, "base", "base")
    git(tmp_path, "clone", "-q", "--bare", str(seed), str(github))
    add_project(tmp_path / "store", me, "o/app")
    gate_config = tmp_path / "gate.gitconfig"
    gate_config.write_text(
        f'[url "file://{github}"]\n\tinsteadOf = https://github.com/o/app.git\n'
    )
    wrapper = tmp_path / "gate"
    wrapper.write_text(
        f"""#!{sys.executable}
import importlib.util, os, sys
from pathlib import Path
os.environ.update(SUDO_UID="{os.getuid()}", GIT_CONFIG_GLOBAL="{gate_config}")
sys.path.insert(0, "{ROOT / "bin"}")
spec = importlib.util.spec_from_file_location("gate", "{GATE}")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
gate.STORE = Path("{tmp_path / "store"}")
gate.WORK = Path("{tmp_path / "work"}")
gate.main(sys.argv[1:])
"""
    )
    wrapper.chmod(0o755)
    client_config = tmp_path / "client.gitconfig"
    client_config.write_text(
        f'[url "ext::{wrapper} %S"]\n\tinsteadOf = https://github.com/o/app.git\n'
        '[protocol "ext"]\n\tallow = always\n'
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(client_config))
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", "https://github.com/o/app.git", str(clone))
    return github, clone


def push(clone, *args):
    return subprocess.run(
        ["git", "push", "origin", *args],
        cwd=clone,
        capture_output=True,
        text=True,
        check=False,
    )


def test_fetch_reads_github_through_the_gate(transport, tmp_path):
    github, clone = transport
    assert (
        git(clone, "symbolic-ref", "refs/remotes/origin/HEAD")
        == "refs/remotes/origin/main"
    )
    upstream = tmp_path / "upstream"
    git(tmp_path, "clone", "-q", str(github), str(upstream))
    sha = commit(upstream, "next", "next")
    git(upstream, "push", "-q", "origin", "main")

    git(clone, "fetch", "-q", "origin")

    assert git(clone, "rev-parse", "origin/main") == sha


def test_push_of_an_issue_branch_reaches_github(transport):
    github, clone = transport
    git(clone, "switch", "-q", "-c", "issue-5-x")
    sha = commit(clone, "change", "change")

    result = push(clone, "issue-5-x")

    assert result.returncode == 0, result.stderr
    assert git(github, "rev-parse", "issue-5-x") == sha


def test_push_to_the_default_branch_is_refused(transport):
    github, clone = transport
    before = git(github, "rev-parse", "main")
    commit(clone, "change", "change")

    result = push(clone, "main")

    assert result.returncode != 0
    assert "refs/heads/main is the default branch" in result.stderr
    assert git(github, "rev-parse", "main") == before


def test_push_of_another_branch_is_refused(transport):
    _github, clone = transport
    result = push(clone, "HEAD:refs/heads/release")
    assert "is no issue-* or bump-pipeline-* branch" in result.stderr


def test_force_push_is_refused(transport):
    github, clone = transport
    git(clone, "switch", "-q", "-c", "issue-5-x")
    commit(clone, "one", "one")
    assert push(clone, "issue-5-x").returncode == 0
    pushed = git(github, "rev-parse", "issue-5-x")
    git(clone, "commit", "-q", "--amend", "-m", "rewritten")

    result = push(clone, "--force", "issue-5-x")

    assert "no fast-forward" in result.stderr
    assert git(github, "rev-parse", "issue-5-x") == pushed


def test_deleting_a_branch_is_refused(transport):
    github, clone = transport
    git(clone, "switch", "-q", "-c", "issue-5-x")
    assert push(clone, "issue-5-x").returncode == 0

    result = push(clone, "--delete", "issue-5-x")

    assert "deleting refs/heads/issue-5-x is not allowed" in result.stderr
    assert git(github, "rev-parse", "issue-5-x")


# merge


def pull(sha=SHA, state="open", base="main"):
    return {
        "number": 5,
        "state": state,
        "head": {"sha": sha},
        "base": {"ref": base, "sha": "b" * 40},
        "body": "Closes #4",
        "title": "t",
    }


def attested(verdict=attestation.APPROVE, sha=SHA, key=KEY, state="COMMENTED"):
    body = f"Verdict: x\n\n{attestation.line(key, 5, sha, verdict, 's1')}"
    return {"body": body, "commit_id": sha, "state": state}


GREEN = [{"name": "CI", "status": "completed", "conclusion": "success"}]


@pytest.fixture
def github(gate, monkeypatch):
    state = {
        "pull": pull(),
        "reviews": [attested()],
        "threads": [{"isResolved": True}],
        "runs": GREEN,
        "merged": [],
    }
    monkeypatch.setattr(
        gate, "pull_request", lambda p, pr, sha: gate_pull(gate, state, pr, sha)
    )
    monkeypatch.setattr(gate, "reviews", lambda p, pr: state["reviews"])
    monkeypatch.setattr(gate, "threads", lambda p, pr: state["threads"])
    monkeypatch.setattr(gate, "runs", lambda p, sha: state["runs"])

    def gh(self, *args, input=None):
        if args[:2] == ("pr", "merge"):
            state["merged"].append(args)
            return "merged\n"
        raise AssertionError(args)

    def gh_json(self, *args):
        assert args == ("api", "repos/o/app")
        return {"default_branch": "main"}

    monkeypatch.setattr(gate.Project, "gh", gh)
    monkeypatch.setattr(gate.Project, "gh_json", gh_json)
    return state


def gate_pull(gate, state, pr, sha):
    found = state["pull"]
    if found["head"]["sha"] != sha:
        raise gate.Refused(f"the head of #{pr} is {found['head']['sha']}, not {sha}")
    return found


def test_merge_with_every_gate_passed(gate, project, github, capsys):
    gate.merge(project, 5, SHA)
    assert github["merged"] == [
        ("pr", "merge", "5", "--squash", "--match-head-commit", SHA)
    ]


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"reviews": []}, "no attested approve"),
        ({"reviews": [attested(key="wrong")]}, "no attested approve"),
        ({"reviews": [attested(sha="c" * 40)]}, "no attested approve"),
        (
            {"reviews": [attested(), attested(attestation.CHANGES_REQUESTED)]},
            "no attested approve",
        ),
        ({"reviews": [attested(state="DISMISSED")]}, "no attested approve"),
        (
            {
                "reviews": [
                    {"body": "Verdict: approve", "commit_id": SHA, "state": "COMMENTED"}
                ]
            },
            "no attested approve",
        ),
        ({"threads": [{"isResolved": False}]}, "1 review threads are open"),
        (
            {"runs": [{"name": "CI", "status": "completed", "conclusion": "failure"}]},
            "runs not passed: CI",
        ),
        (
            {"runs": [{"name": "CI", "status": "in_progress", "conclusion": ""}]},
            "runs not passed: CI",
        ),
        ({"runs": []}, "runs not passed: no CI run"),
        ({"pull": pull(base="release")}, "targets release"),
        ({"pull": pull(sha="c" * 40)}, "the head of #5 is"),
    ],
)
def test_merge_refuses(gate, project, github, change, problem):
    github.update(change)
    with pytest.raises(gate.Refused, match=problem):
        gate.merge(project, 5, SHA)
    assert github["merged"] == []


# review


@pytest.fixture
def reviewing(gate, project, monkeypatch, tmp_path):
    posted, gh_calls = [], []
    monkeypatch.setattr(gate, "pull_request", lambda p, pr, sha: pull())
    monkeypatch.setattr(gate, "refresh_mirror", lambda p: None)
    monkeypatch.setattr(gate, "write_context", lambda p, pull, sha, folder: None)
    monkeypatch.setattr(gate, "export", lambda p, rev, folder: folder.mkdir())
    monkeypatch.setattr(
        gate,
        "post_review",
        lambda p, pr, sha, body, comments: posted.append((body, comments)),
    )

    def gh(self, *args, input=None):
        gh_calls.append((args, input))
        return "https://github.com/o/app/issues/99\n"

    monkeypatch.setattr(gate.Project, "gh", gh)
    result = {
        "verdict": "approve",
        "summary": "Passt.\n\nDetails.",
        "comments": [],
        "resolve": [],
        "followups": [],
    }
    monkeypatch.setattr(gate, "claude_review", lambda p, tmp, session: result)
    return result, posted, gh_calls


def test_review_posts_an_attested_verdict(gate, project, reviewing, capsys):
    _result, posted, _ = reviewing
    gate.review(project, 5, SHA)
    body, _comments = posted[0]
    assert body.startswith("Verdict: approve\n\nPasst.")
    assert attestation.verdict(body, KEY, 5, SHA) == attestation.APPROVE
    assert capsys.readouterr().out == (
        "STATUS: done\nSUMMARY: Passt.\nVERDICT: approve\nNEXT: CI\n"
    )


def test_review_with_changes_requested(gate, project, reviewing, capsys):
    result, posted, _ = reviewing
    result.update(
        verdict="changes requested",
        comments=[{"path": "a.py", "line": 3, "body": "Fehler"}],
    )
    gate.review(project, 5, SHA)
    body, comments = posted[0]
    assert attestation.verdict(body, KEY, 5, SHA) == attestation.CHANGES_REQUESTED
    assert comments == [{"path": "a.py", "line": 3, "body": "Fehler", "side": "RIGHT"}]
    assert "VERDICT: changes requested" in capsys.readouterr().out


def test_review_creates_followups_and_resolves_threads(gate, project, reviewing):
    result, posted, gh_calls = reviewing
    result.update(followups=[{"title": "T", "body": "B"}], resolve=["PRRT_1"])
    gate.review(project, 5, SHA)
    assert gh_calls[0] == (
        ("issue", "create", "--label", "followup", "--title", "T", "--body-file", "-"),
        "B",
    )
    assert gh_calls[1][0][:2] == ("api", "graphql")
    assert "id=PRRT_1" in gh_calls[1][0]
    assert "Folge-Issues: https://github.com/o/app/issues/99" in posted[0][0]


@pytest.mark.parametrize("secret", [TOKEN, KEY])
def test_review_output_with_a_secret_is_not_posted(gate, project, reviewing, secret):
    result, posted, _ = reviewing
    result["summary"] = f"leak {secret}"
    with pytest.raises(gate.Refused, match="contains a secret"):
        gate.review(project, 5, SHA)
    assert posted == []


def test_review_output_with_a_secret_of_another_project_is_not_posted(
    gate, project, reviewing, tmp_path
):
    add_project(tmp_path / "store", "other", "o/site", token="github_pat_other")
    result, posted, _ = reviewing
    result["summary"] = "leak github_pat_other"
    with pytest.raises(gate.Refused, match="contains a secret"):
        gate.review(project, 5, SHA)
    assert posted == []


def test_claude_review_runs_without_token_and_project_settings(
    gate, project, monkeypatch, tmp_path
):
    calls = []
    output = {"structured_output": {"verdict": "approve"}}

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(
            args, 0, stdout=json.dumps(output), stderr=""
        )

    monkeypatch.setattr(gate.shutil, "which", lambda name, path: "/bin/claude")
    monkeypatch.setattr(gate.subprocess, "run", run)
    (tmp_path / "tree").mkdir()

    assert gate.claude_review(project, tmp_path, "s1") == {"verdict": "approve"}

    args, kwargs = calls[0]
    assert "--restricted" in args
    assert "--setting-sources" not in args
    settings = json.loads(args[args.index("--settings") + 1])
    assert "Read(//proc/**)" in settings["permissions"]["deny"]
    assert str(tmp_path / "tree") in args
    assert args[args.index("--tools") + 1] == "Read,Grep,Glob"
    assert args[-2:] == ["--tools", "Read,Grep,Glob"]
    assert not any(TOKEN in value for value in kwargs["env"].values())
    assert "GH_TOKEN" not in kwargs["env"]
    assert kwargs["cwd"] == tmp_path / "base"
    assert str(tmp_path / "context") in kwargs["input"]


def test_manual_review_only_for_root(gate, project, monkeypatch):
    monkeypatch.setenv("SUDO_UID", "1000")
    with pytest.raises(gate.Refused, match="only root"):
        gate.manual_review("x", 5, SHA, "approve")


def test_manual_review_of_root(gate, project, me, monkeypatch):
    posted = []
    monkeypatch.setenv("SUDO_UID", "0")
    monkeypatch.setattr(gate, "pull_request", lambda p, pr, sha: pull())
    monkeypatch.setattr(
        gate, "post_review", lambda p, pr, sha, body, c: posted.append(body)
    )
    gate.manual_review(me, 5, SHA, "approve")
    assert attestation.verdict(posted[0], KEY, 5, SHA) == attestation.APPROVE


def test_post_review_folds_comments_into_body_on_failure(gate, project, monkeypatch):
    calls = []

    def gh(self, *args, input=None):
        calls.append(json.loads(input))
        if len(calls) == 1:
            raise gate.Refused("422")
        return ""

    monkeypatch.setattr(gate.Project, "gh", gh)
    body = f"Verdict: approve\n\nx\n\n{gate.FOOTER}\n\n<!-- a -->"
    gate.post_review(project, 5, SHA, body, [{"path": "a.py", "line": 9, "body": "c"}])
    assert calls[1]["comments"] == []
    assert "`a.py:9`: c" in calls[1]["body"]
    assert calls[1]["body"].endswith("<!-- a -->")


def test_review_prompt_names_only_known_placeholders():
    prompt = (ROOT / "host" / "gate-review.md").read_text()
    assert prompt.format(context="C", tree="T", rules="R")


def test_usage(gate):
    with pytest.raises(SystemExit) as error:
        gate.main([])
    assert "Commands" in error.value.code
