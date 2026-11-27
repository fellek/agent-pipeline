#!/usr/bin/env python3
"""Gate of the host: the only holder of the GitHub token and review key of a project.

install-gate.sh installs it as /opt/pipeline/gate, owned by root. The autopilot's
Linux user has no token and calls it as `sudo -n -u pipeline-gate /opt/pipeline/gate
<command>` (bin/gate). The calling user (SUDO_UID) selects the project, so on a
shared gate each autopilot reaches only its own repository. Pushing to the default
branch, merging and approving are impossible from the model's session this way,
whether or not GitHub enforces a ruleset.

Commands:
  git-upload-pack | git-receive-pack    git transport (ext:: URL of the project)
  pre-receive                           hook of the mirror: issue and bump branches,
                                        fast-forward only, then pushed to GitHub
  gh <args>                             gh with the token, allowed commands only
  check                                 print the repository the token reaches
  review <pr> <sha>                     review by a fresh `claude -p`, posted with
                                        an attestation; prints the result block;
                                        at most REVIEW_LIMIT per head
  review --manual <user> <pr> <sha> approve|changes-requested
                                        only for root: the maintainer's verdict
  carry <pr> <sha>                      approve sha without a review if it only
                                        merges the default branch into an approved
                                        head, touching no file of the pull request
  merge <pr> <sha>                      squash merge after checking every gate
  release <user> <tag> <sha> [<notes>]  only for root: starts the workflow release
                                        for sha, the head of the default branch,
                                        with the upgrade notes
"""

import base64
import fcntl
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import attestation
import trust

STORE = Path("/etc/pipeline-gate/projects")
WORK = Path("/var/lib/pipeline-gate/projects")
HERE = Path(__file__).resolve().parent
REVIEW_PROMPT = HERE / "gate-review.md"
WORKFLOW_RULES = HERE / "workflow.md"
PUSHABLE = re.compile(r"refs/heads/(issue|bump-pipeline|bump-plugin)-[^/]+")
ZERO = "0" * 40
# Runs of `claude -p` per head; more only by the manual verdict of the maintainer.
REVIEW_LIMIT = 2
# Only these reach the review: content of others could steer it (prompt injection).
TRUSTED = trust.TRUSTED

GH_COMMANDS = {
    "issue": {"view", "list", "comment", "create", "edit", "close", "reopen"},
    "pr": {"view", "list", "create", "diff", "comment", "edit", "close"},
    "run": {"list", "view", "watch"},
    "release": {"view", "list"},
    "label": {"list", "create"},
}
# These flags of gh read a file of the gate user unless their value is stdin.
FILE_FLAGS = {"-F", "--body-file", "--input"}
API_VALUE_FLAGS = {
    "-X",
    "--method",
    "-f",
    "-F",
    "--field",
    "--raw-field",
    "-H",
    "--header",
    "--input",
    "-q",
    "--jq",
    "-t",
    "--template",
    "--cache",
    "-p",
    "--preview",
    "--hostname",
}
API_SWITCHES = {"--paginate", "--slurp", "-i", "--include", "--silent", "--verbose"}
# A short flag with its value attached, such as -F<file> or -XPUT.
ATTACHED = re.compile(r"-[^-].+")
API_WRITES = [
    ("POST", re.compile(r"issues/\d+/comments")),
    ("PATCH", re.compile(r"issues/comments/\d+")),
    ("POST", re.compile(r"pulls/\d+/comments/\d+/replies")),
]
THREADS_QUERY = """
query($owner: String!, $repo: String!, $pr: Int!, $endCursor: String) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $pr) {
      reviewThreads(first: 100, after: $endCursor) {
        pageInfo { hasNextPage endCursor }
        nodes { id isResolved path line
          comments(first: 20) { nodes { author { login } authorAssociation body url } } }
      }
    }
  }
}
"""
RESOLVE = "mutation($id: ID!) { resolveReviewThread(input: {threadId: $id}) { thread { id } } }"
REVIEW_SCHEMA = {
    "type": "object",
    "required": ["verdict", "summary", "comments", "resolve", "followups"],
    "properties": {
        "verdict": {"enum": ["approve", "changes requested"]},
        "summary": {"type": "string"},
        "comments": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["path", "line", "body"],
                "properties": {
                    "path": {"type": "string"},
                    "line": {"type": "integer"},
                    "body": {"type": "string"},
                },
            },
        },
        "resolve": {"type": "array", "items": {"type": "string"}},
        "followups": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["title", "body"],
                "properties": {"title": {"type": "string"}, "body": {"type": "string"}},
            },
        },
    },
}
REVIEW_DENY = ["Read(//etc/pipeline-gate/**)", "Read(//proc/**)", "Read(~/.claude/**)"]
PLUGIN_JSON = ".claude-plugin/plugin.json"
FOOTER = "---\n_Generated by [Claude Code](https://claude.ai/code)_"


class Refused(Exception):
    pass


class Project:
    def __init__(self, user):
        store = STORE / user
        if not store.is_dir():
            raise Refused(f"no project for user {user}")
        self.user = user
        self.repo = (store / "repo").read_text().strip()
        self.token = (store / "token").read_text().strip()
        self.key = (store / "review-key").read_text().strip()
        self.work = WORK / user
        self.mirror = self.work / "mirror.git"
        self.url = f"https://github.com/{self.repo}.git"

    def env(self):
        """Environment of gh and git; the token never appears in an argument."""
        basic = base64.b64encode(f"x-access-token:{self.token}".encode()).decode()
        home = pwd.getpwuid(os.geteuid()).pw_dir
        return {
            "PATH": f"{home}/.local/bin:/usr/local/bin:/usr/bin:/bin",
            "HOME": home,
            "GH_TOKEN": self.token,
            "GH_REPO": self.repo,
            "GH_PROMPT_DISABLED": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.https://github.com/.extraHeader",
            "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}",
        }

    def run(self, *args, **kwargs):
        self.work.mkdir(parents=True, exist_ok=True)
        kwargs.setdefault("cwd", self.work)
        kwargs.setdefault("env", {**os.environ, **self.env()})
        check = kwargs.pop("check", False)
        return subprocess.run(list(args), check=check, **kwargs)

    def gh(self, *args, input=None):
        result = self.run("gh", *args, input=input, capture_output=True, text=True)
        if result.returncode != 0:
            raise Refused(f"gh {' '.join(args[:2])} failed: {result.stderr.strip()}")
        return result.stdout

    def gh_json(self, *args):
        return json.loads(self.gh(*args))


def all_secrets():
    """Tokens and keys of all projects: the review runs as the user of all of them."""
    return [
        path.read_text().strip()
        for project in STORE.iterdir()
        for path in (project / "token", project / "review-key")
        if path.exists()
    ]


def caller():
    uid = os.environ.get("SUDO_UID")
    if uid is None:
        raise Refused("run the gate through sudo")
    return int(uid)


def project_of_caller():
    return Project(pwd.getpwuid(caller()).pw_name)


# git transport


def refresh_mirror(project):
    """Bring the mirror in line with GitHub, including its default branch."""
    project.work.mkdir(parents=True, exist_ok=True)
    # Two git calls of the user, as the clone of update-host and the poller, would
    # fetch at once, and git fails the fetch that finds a ref locked by the other.
    with open(project.work / "mirror.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not project.mirror.exists():
            project.run(
                "git", "init", "--quiet", "--bare", str(project.mirror), check=True
            )
            hook = project.mirror / "hooks" / "pre-receive"
            # sudo runs the gate by its absolute path, so argv[0] names the installed gate.
            hook.write_text(
                f'#!/bin/sh\nexec "{Path(sys.argv[0]).resolve()}" pre-receive\n'
            )
            hook.chmod(0o755)
        git = ["git", "-C", str(project.mirror)]
        project.run(
            *git,
            "fetch",
            "--quiet",
            "--prune",
            project.url,
            "+refs/heads/*:refs/heads/*",
            "+refs/tags/*:refs/tags/*",
            check=True,
            stdout=sys.stderr,
        )
        head = project.run(
            *git,
            "ls-remote",
            "--symref",
            project.url,
            "HEAD",
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        if match := re.match(r"ref: (refs/heads/\S+)\tHEAD", head):
            project.run(*git, "symbolic-ref", "HEAD", match.group(1), check=True)


def serve(project, service):
    # Variables such as GIT_DIR of the calling git must not reach the mirror.
    local = subprocess.run(
        ["git", "rev-parse", "--local-env-vars"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    for name in local:
        os.environ.pop(name, None)
    refresh_mirror(project)
    sys.stdout.flush()
    os.execvpe(
        "git",
        ["git", service.removeprefix("git-"), str(project.mirror)],
        {**os.environ, **project.env()},
    )


def push_problem(ref, old, new, default_ref, is_ancestor):
    if ref == default_ref:
        return f"{ref} is the default branch"
    if not PUSHABLE.fullmatch(ref):
        return f"{ref} is no issue-*, bump-pipeline-* or bump-plugin-* branch"
    if new == ZERO:
        return f"deleting {ref} is not allowed"
    if old != ZERO and not is_ancestor(old, new):
        return f"{ref} is no fast-forward, force pushes are not allowed"
    return None


def pre_receive(project, lines):
    """Checks every pushed ref, then pushes it to GitHub before the mirror takes it."""
    git = ["git", "-C", str(project.mirror)]
    default_ref = project.run(
        *git, "symbolic-ref", "HEAD", capture_output=True, text=True, check=True
    ).stdout.strip()

    def is_ancestor(old, new):
        return (
            project.run(*git, "merge-base", "--is-ancestor", old, new).returncode == 0
        )

    updates = [line.split() for line in lines if line.strip()]
    for old, new, ref in updates:
        if problem := push_problem(ref, old, new, default_ref, is_ancestor):
            raise Refused(problem)
    for old, new, ref in updates:
        pushed = project.run(
            *git,
            "push",
            "--quiet",
            project.url,
            f"{new}:{ref}",
            # The objects come from the quarantine of the push; a local remote would
            # refuse its own ref update under GIT_QUARANTINE_PATH.
            env={
                **{k: v for k, v in os.environ.items() if k != "GIT_QUARANTINE_PATH"},
                **project.env(),
            },
            capture_output=True,
            text=True,
        )
        if pushed.returncode != 0:
            raise Refused(f"GitHub refused {ref}: {pushed.stderr.strip()}")


# gh


def same_repo(name, repo):
    return name.lower().removesuffix(".git") == repo.lower()


def gh_problem(args, repo):
    """Why the gate does not run `gh <args>`, or None."""
    if not args:
        return "gh needs a command"
    if args[0] == "api":
        return api_problem(args[1:], repo)
    command, sub = args[0], (args[1] if len(args) > 1 else "")
    if sub not in GH_COMMANDS.get(command, ()):
        return f"gh {command} {sub} is not allowed through the gate".replace("  ", " ")
    rest = args[2:]
    for i, arg in enumerate(rest):
        if ATTACHED.fullmatch(arg):
            return f"{arg[:2]} needs its value as the next argument through the gate"
        if arg.split("=")[0] == "--recover":
            return "--recover reads a file of the gate user"
        name, _, inline = arg.partition("=")
        value = inline if "=" in arg else (rest[i + 1] if i + 1 < len(rest) else "")
        if name in FILE_FLAGS and value != "-":
            return f"{name} reads only from stdin through the gate: use {name} -"
        if (
            name in ("-R", "--repo")
            and command != "release"
            and not same_repo(value, repo)
        ):
            return f"the gate reaches only {repo}"
    return None


def api_problem(args, repo):
    method, fields, path, query = None, False, None, None
    i = 0
    while i < len(args):
        arg = args[i]
        if ATTACHED.fullmatch(arg):
            return f"{arg[:2]} needs its value as the next argument through the gate"
        name, eq, inline = arg.partition("=")
        if arg.startswith("-") and name not in API_VALUE_FLAGS | API_SWITCHES:
            return f"gh api {name} is not allowed through the gate"
        if name in API_VALUE_FLAGS:
            value = inline if eq else (args[i + 1] if i + 1 < len(args) else "")
            i += 1 if eq else 2
            if name == "--hostname":
                return "gh api --hostname is not allowed through the gate"
            if name in ("-X", "--method"):
                method = value.upper()
            if name in ("-f", "-F", "--field", "--raw-field", "--input"):
                fields = True
            if name == "--input" and value != "-":
                return "--input reads only from stdin through the gate: use --input -"
            if name in ("-F", "--field") and "=@" in value:
                return "file values of -F are not allowed through the gate"
            if name in ("-f", "-F", "--field", "--raw-field") and value.startswith(
                "query="
            ):
                query = value.removeprefix("query=")
            continue
        if not arg.startswith("-") and path is None:
            path = arg.lstrip("/")
        i += 1
    if path is None:
        return "gh api needs a path"
    if path == "graphql":
        if query is None or re.search(r"\b(mutation|subscription)\b", query):
            return "only GraphQL queries are allowed through the gate"
        return None
    parts = path.split("?")[0].split("/")
    if parts[0] == "repos" and (
        len(parts) < 3
        or not (
            parts[1:3] == ["{owner}", "{repo}"] or same_repo("/".join(parts[1:3]), repo)
        )
    ):
        return f"the gate reaches only {repo}"
    method = method or ("POST" if fields else "GET")
    if method == "GET":
        return None
    rest = "/".join(parts[3:]) if parts[0] == "repos" else ""
    if any(method == m and pattern.fullmatch(rest) for m, pattern in API_WRITES):
        return None
    return f"gh api {method} {path} is not allowed through the gate"


COMMENT_PATHS = re.compile(r"repos/[^/]+/[^/]+/issues/(\d+/comments|comments/\d+)")


# The flags of the commands that post an issue comment.
COMMENT_FLAGS = {
    ("issue", "comment"): ("-b", "--body", "-F", "--body-file"),
    ("pr", "comment"): ("-b", "--body", "-F", "--body-file"),
    ("issue", "close"): ("-c", "--comment"),
    ("issue", "reopen"): ("-c", "--comment"),
    ("pr", "close"): ("-c", "--comment"),
}


def marked(text):
    return f"{text}\n\n{trust.MARKER}"


def mark_comment(args, stdin):
    """The arguments and stdin of `gh <args>` with the marker in a comment body."""
    args = list(args)
    flags = COMMENT_FLAGS.get(tuple(args[:2]), ())
    for i, arg in enumerate(args):
        name, eq, value = arg.partition("=")
        if name not in flags:
            continue
        if name in ("-F", "--body-file"):
            return args, marked(stdin())
        if eq:
            args[i] = f"{name}={marked(value)}"
        else:
            args[i + 1] = marked(args[i + 1])
    if args[:1] == ["api"] and any(
        COMMENT_PATHS.fullmatch(a.lstrip("/").partition("?")[0]) for a in args
    ):
        for i, arg in enumerate(args):
            name, eq, value = arg.partition("=")
            if name == "--input":
                body = json.loads(stdin())
                if "body" in body:
                    body["body"] = marked(body["body"])
                return args, json.dumps(body)
            if name not in ("-f", "-F", "--field", "--raw-field"):
                continue
            if eq and value.startswith("body="):
                args[i] = f"{name}={marked(value)}"
            elif not eq and args[i + 1].startswith("body="):
                args[i + 1] = marked(args[i + 1])
    return args, None


def run_gh(project, args):
    if problem := gh_problem(args, project.repo):
        raise Refused(problem)
    args, stdin = mark_comment(args, sys.stdin.read)
    # gh runs git in its working directory, which the caller may keep closed to the
    # gate, as the clone of update-host; GH_REPO names the repository anyway.
    # The absolute path, since a closed parent blocks git while "." itself stays open.
    if not os.access(os.getcwd(), os.R_OK | os.X_OK):
        project.work.mkdir(parents=True, exist_ok=True)
        os.chdir(project.work)
    env = {**os.environ, **project.env()}
    if stdin is None:
        os.execvpe("gh", ["gh", *args], env)
    else:
        done = subprocess.run(
            ["gh", *args], input=stdin, text=True, env=env, check=False
        )
        sys.exit(done.returncode)


# review and merge


def pull_request(project, pr, sha):
    pull = project.gh_json("api", f"repos/{project.repo}/pulls/{pr}")
    if pull["state"] != "open":
        raise Refused(f"#{pr} is not open")
    if pull["head"]["sha"] != sha:
        raise Refused(f"the head of #{pr} is {pull['head']['sha']}, not {sha}")
    return pull


def reviews(project, pr):
    pages = project.gh_json(
        "api",
        "--paginate",
        "--slurp",
        f"repos/{project.repo}/pulls/{pr}/reviews?per_page=100",
    )
    return [
        review
        for page in pages
        for review in page
        if review["author_association"] in TRUSTED
    ]


def threads(project, pr):
    owner, name = project.repo.split("/")
    pages = project.gh_json(
        "api",
        "graphql",
        "--paginate",
        "--slurp",
        "-F",
        f"owner={owner}",
        "-F",
        f"repo={name}",
        "-F",
        f"pr={pr}",
        "-f",
        f"query={THREADS_QUERY}",
    )
    return [
        {
            **thread,
            "comments": {
                "nodes": trusted(thread["comments"]["nodes"], "authorAssociation")
            },
        }
        for page in pages
        for thread in page["data"]["repository"]["pullRequest"]["reviewThreads"][
            "nodes"
        ]
        if thread["comments"]["nodes"][0]["authorAssociation"] in TRUSTED
    ]


def trusted(items, key):
    return [item for item in items if item[key] in TRUSTED]


def runs(project, sha):
    return project.gh_json(
        "run",
        "list",
        "--commit",
        sha,
        "--limit",
        "100",
        "--json",
        "name,status,conclusion,url",
    )


def merge_problems(project, pr, sha):
    pull = pull_request(project, pr, sha)
    problems = []
    default = project.gh_json("api", f"repos/{project.repo}")["default_branch"]
    if pull["base"]["ref"] != default:
        problems.append(f"#{pr} targets {pull['base']['ref']}, not {default}")
    if (
        attestation.latest_verdict(reviews(project, pr), project.key, pr, sha)
        != attestation.APPROVE
    ):
        problems.append(f"no attested approve on {sha}")
    if open_threads := [t for t in threads(project, pr) if not t["isResolved"]]:
        problems.append(f"{len(open_threads)} review threads are open")
    if failed := attestation.failed_runs(runs(project, sha)):
        problems.append(f"runs not passed: {', '.join(failed)}")
    return problems


def merge(project, pr, sha):
    if problems := merge_problems(project, pr, sha):
        raise Refused("; ".join(problems))
    print(
        project.gh("pr", "merge", str(pr), "--squash", "--match-head-commit", sha),
        end="",
    )


def contains_secret(value, secrets):
    text = json.dumps(value)
    return any(secret and secret in text for secret in secrets)


def review_body(verdict, text, pr, sha, session, key):
    title = "approve" if verdict == attestation.APPROVE else "changes requested"
    line = attestation.line(key, pr, sha, verdict, session)
    return f"Verdict: {title}\n\n{text}\n\n{FOOTER}\n\n{line}"


def post_review(project, pr, sha, body, comments):
    review = {"commit_id": sha, "event": "COMMENT", "body": body, "comments": comments}
    path = f"repos/{project.repo}/pulls/{pr}/reviews"
    try:
        project.gh(
            "api", "--method", "POST", path, "--input", "-", input=json.dumps(review)
        )
    except Refused:
        # A line outside the diff fails the whole review, so the findings go to the body.
        folded = "\n\n".join(
            f"`{c['path']}:{c['line']}`: {c['body']}" for c in comments
        )
        review = {
            **review,
            "comments": [],
            "body": body.replace(f"\n\n{FOOTER}", f"\n\n{folded}\n\n{FOOTER}", 1),
        }
        project.gh(
            "api", "--method", "POST", path, "--input", "-", input=json.dumps(review)
        )


def pages(project, path):
    found = project.gh_json("api", "--paginate", "--slurp", f"{path}?per_page=100")
    return [item for page in found for item in page]


def issue_text(project, number):
    """The issue as issue-text.py prints it; refused as there."""
    base = f"repos/{project.repo}/issues/{number}"
    issue = project.gh_json("api", base)
    if issue["author_association"] not in TRUSTED:
        edited = project.gh(
            "api",
            "graphql",
            "-F",
            f"owner={project.repo.split('/')[0]}",
            "-F",
            f"repo={project.repo.split('/')[1]}",
            "-F",
            f"n={number}",
            "-f",
            f"query={trust.EDITED_QUERY}",
            "--jq",
            ".data.repository.issue.lastEditedAt",
        ).strip()

        def permission(login):
            try:
                path = f"repos/{project.repo}/collaborators/{login}/permission"
                return project.gh_json("api", path)["permission"]
            except Refused:
                return None

        if not trust.approved(pages(project, f"{base}/events"), edited, permission):
            raise Refused(f"#{number} changed after the latest label of a writer")
    return {
        "number": issue["number"],
        "title": issue["title"],
        "body": issue["body"],
        "comments": [
            {"author": c["user"]["login"], "body": c["body"]}
            for c in trust.trusted_comments(
                pages(project, f"{base}/comments"), "author_association"
            )
        ],
    }


def write_context(project, pull, sha, folder):
    """The data of the review: issue, pull request, threads, diff and runs."""
    pr = pull["number"]
    issue = re.search(r"(?i)\bcloses #(\d+)", pull["body"] or "")
    data = {
        "pull_request.json": {k: pull[k] for k in ("number", "title", "body")},
        "reviews.json": reviews(project, pr),
        "threads.json": threads(project, pr),
        "runs.json": runs(project, sha),
    }
    if issue:
        number = issue.group(1)
        data["issue.json"] = issue_text(project, number)
    for name, value in data.items():
        (folder / name).write_text(json.dumps(value, indent=2, ensure_ascii=False))
    diff = project.run(
        "git",
        "-C",
        str(project.mirror),
        "diff",
        f"{pull['base']['sha']}...{sha}",
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    (folder / "diff.patch").write_text(diff)


def export(project, rev, folder):
    folder.mkdir()
    archive = project.run(
        "git",
        "-C",
        str(project.mirror),
        "archive",
        rev,
        check=True,
        capture_output=True,
    ).stdout
    subprocess.run(["tar", "-x", "-C", str(folder)], input=archive, check=True)
    # A symlink of the pull request could point out of the export, for example
    # to the mirror of another project.
    subprocess.run(["find", str(folder), "-type", "l", "-delete"], check=True)


def claude_review(project, tmp, session):
    claude = shutil.which("claude", path=project.env()["PATH"])
    if claude is None:
        raise Refused("claude is not installed for the gate user")
    prompt = REVIEW_PROMPT.read_text().format(
        context=tmp / "context", tree=tmp / "tree", rules=WORKFLOW_RULES
    )
    env = {
        k: v
        for k, v in project.env().items()
        if not k.startswith(("GH_", "GIT_CONFIG"))
    }
    result = subprocess.run(
        [
            claude,
            "-p",
            "--model",
            "opus",
            "--effort",
            "high",
            # No settings files, so no hooks of the pull request run as the gate
            # user, and the file tools stay in the directories below: the gate
            # user can read the secrets and work trees of every project.
            "--restricted",
            "--settings",
            json.dumps({"permissions": {"deny": REVIEW_DENY}}),
            "--strict-mcp-config",
            "--permission-mode",
            "dontAsk",
            "--no-session-persistence",
            "--session-id",
            session,
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(REVIEW_SCHEMA),
            "--add-dir",
            str(tmp / "context"),
            "--add-dir",
            str(tmp / "tree"),
            "--add-dir",
            str(HERE),
            "--tools",
            "Read,Grep,Glob",
        ],
        # The base, so CLAUDE.md comes from the default branch, not the pull request.
        cwd=tmp / "base",
        env=env,
        input=prompt,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise Refused(
            f"claude failed: {(result.stderr or result.stdout).strip()[-500:]}"
        )
    output = json.loads(result.stdout)
    return output.get("structured_output") or json.loads(output["result"])


def review(project, pr, sha):
    project.work.mkdir(parents=True, exist_ok=True)
    # Counting, reviewing and posting in one lock, or parallel calls roll the dice
    # past the limit.
    with open(project.work / "review.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        _review(project, pr, sha)


def _review(project, pr, sha):
    pull = pull_request(project, pr, sha)
    if (
        attestation.gate_reviews(reviews(project, pr), project.key, pr, sha)
        >= REVIEW_LIMIT
    ):
        raise Refused(
            f"{sha} has {REVIEW_LIMIT} reviews already; "
            f"the maintainer decides with `gate review --manual` as root"
        )
    refresh_mirror(project)
    session = str(uuid.uuid4())
    with tempfile.TemporaryDirectory(dir=project.work) as name:
        tmp = Path(name)
        (tmp / "context").mkdir()
        write_context(project, pull, sha, tmp / "context")
        export(project, sha, tmp / "tree")
        export(project, pull["base"]["sha"], tmp / "base")
        result = claude_review(project, tmp, session)
    if contains_secret(result, all_secrets()):
        raise Refused("the review output contains a secret of the gate")
    verdict = (
        attestation.APPROVE
        if result["verdict"] == "approve"
        else attestation.CHANGES_REQUESTED
    )
    created = [
        project.gh(
            "issue",
            "create",
            "--label",
            "followup",
            "--title",
            f["title"],
            "--body-file",
            "-",
            input=f["body"],
        ).strip()
        for f in result["followups"]
    ]
    for thread in result["resolve"]:
        project.gh("api", "graphql", "-f", f"query={RESOLVE}", "-f", f"id={thread}")
    text = result["summary"].strip()
    if created:
        text += "\n\nFolge-Issues: " + " ".join(created)
    comments = [{**c, "side": "RIGHT"} for c in result["comments"]]
    post_review(
        project,
        pr,
        sha,
        review_body(verdict, text, pr, sha, session, project.key),
        comments,
    )
    title = "approve" if verdict == attestation.APPROVE else "changes requested"
    first = text.splitlines()[0] if text else ""
    print(
        f"STATUS: done\nSUMMARY: {first}\nVERDICT: {title}\n"
        f"NEXT: {'CI' if verdict == attestation.APPROVE else 'fix-review'}"
    )


def carry(project, pr, sha):
    pull = pull_request(project, pr, sha)
    refresh_mirror(project)

    def git(*args):
        result = project.run(
            "git", "-C", str(project.mirror), *args, capture_output=True, text=True
        )
        return result.returncode, result.stdout.strip()

    parents = git("rev-list", "--parents", "-n", "1", sha)[1].split()[1:]
    if len(parents) != 2:
        raise Refused(f"{sha} is not a merge commit")
    approved, merged = parents
    if (
        attestation.latest_verdict(reviews(project, pr), project.key, pr, approved)
        != attestation.APPROVE
    ):
        raise Refused(f"no attested approve on {approved}")
    # Not the base of the pull request: the session can point it at its own branch.
    default = project.gh_json("api", f"repos/{project.repo}")["default_branch"]
    if pull["base"]["ref"] != default:
        raise Refused(f"#{pr} targets {pull['base']['ref']}, not {default}")
    if git("merge-base", "--is-ancestor", merged, f"refs/heads/{default}")[0] != 0:
        raise Refused(f"{merged} is not on {default}")
    # The tree of a clean merge, so a merge commit cannot carry changes of its own.
    code, tree = git("merge-tree", "--write-tree", approved, merged)
    if code != 0 or tree.split()[0] != git("rev-parse", f"{sha}^{{tree}}")[1]:
        raise Refused(f"{sha} is not a clean merge of {approved} and {merged}")
    base = git("merge-base", approved, merged)[1]
    # Without renames, so an edit of the default branch cannot move into a renamed file.
    ours = set(
        git("diff", "--no-renames", "--name-only", "-z", base, approved)[1].split("\0")
    )
    theirs = set(
        git("diff", "--no-renames", "--name-only", "-z", base, merged)[1].split("\0")
    )
    if both := sorted((ours & theirs) - {""}):
        raise Refused(f"{default} changed files of the pull request: {' '.join(both)}")
    text = (
        f"Approve von {approved} übernommen: {sha} merged nur {default} ({merged}), "
        "ohne Dateien des Pull Requests zu ändern."
    )
    body = review_body(attestation.APPROVE, text, pr, sha, "carry", project.key)
    post_review(project, pr, sha, body, [])


def manual_review(user, pr, sha, verdict):
    if caller() != 0:
        raise Refused("only root can post a manual verdict")
    if verdict not in (attestation.APPROVE, attestation.CHANGES_REQUESTED):
        raise Refused(
            f"verdict must be {attestation.APPROVE} or {attestation.CHANGES_REQUESTED}"
        )
    project = Project(user)
    pull_request(project, pr, sha)
    body = review_body(
        verdict, "Verdict des Maintainers.", pr, sha, "manual", project.key
    )
    post_review(project, pr, sha, body, [])


def release(user, tag, sha, notes=""):
    # The update timer of every host installs a release, so the session never starts one.
    if caller() != 0:
        raise Refused("only root can start a release")
    project = Project(user)
    repo = project.repo
    default = project.gh_json("api", f"repos/{repo}")["default_branch"]
    head = project.gh_json("api", f"repos/{repo}/commits/{default}")["sha"]
    if head != sha:
        raise Refused(f"{default} is at {head}, not {sha}")
    content = project.gh_json("api", f"repos/{repo}/contents/{PLUGIN_JSON}?ref={sha}")
    version = json.loads(base64.b64decode(content["content"]))["version"]
    if tag != f"v{version}":
        raise Refused(f"{tag} is not v{version} of {PLUGIN_JSON}")
    if tag in {r["tag_name"] for r in pages(project, f"repos/{repo}/releases")}:
        raise Refused(f"{tag} is released already")
    project.gh(
        "workflow",
        "run",
        "release.yml",
        "--ref",
        default,
        "-f",
        f"tag={tag}",
        "-f",
        f"sha={sha}",
        "-f",
        f"notes={notes}",
    )
    print(
        f"release {tag} started: https://github.com/{repo}/actions/workflows/release.yml"
    )


def main(argv):
    try:
        match argv:
            case ["git-upload-pack" | "git-receive-pack" as service]:
                serve(project_of_caller(), service)
            case ["pre-receive"]:
                pre_receive(project_of_caller(), sys.stdin.read().splitlines())
            case ["gh", *args]:
                run_gh(project_of_caller(), args)
            case ["check"]:
                project = project_of_caller()
                print(
                    project.gh("api", f"repos/{project.repo}", "--jq", ".full_name"),
                    end="",
                )
            case ["review", "--manual", user, pr, sha, verdict] if pr.isdecimal():
                manual_review(user, int(pr), sha, verdict)
            case ["review", pr, sha] if pr.isdecimal():
                review(project_of_caller(), int(pr), sha)
            case ["carry", pr, sha] if pr.isdecimal():
                carry(project_of_caller(), int(pr), sha)
            case ["merge", pr, sha] if pr.isdecimal():
                merge(project_of_caller(), int(pr), sha)
            case ["release", user, tag, sha, *notes] if len(notes) <= 1:
                release(user, tag, sha, *notes)
            case _:
                sys.exit(__doc__)
    except Refused as error:
        sys.exit(f"gate: {error}")


if __name__ == "__main__":
    main(sys.argv[1:])
