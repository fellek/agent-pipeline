#!/usr/bin/env python3
"""PreToolUse hook: blocks Bash commands that push to the default branch (exit 2).

The default branch is read locally, without a network call, from
refs/remotes/<remote>/HEAD of the remote pushed to, in the repository the push runs
in. If that ref is not set or points to a deleted branch, main, master and the
deleted branch are protected. A URL or path is matched against the URLs of the
configured remotes; if none matches, the default branches of all remotes are
protected. Without a remote, the push remote comes from the git config, and
without a refspec, the destination follows remote.<remote>.push and push.default.
"""

import json
import os
import shlex
import subprocess
import sys

FALLBACK_BRANCHES = {"main", "master"}
SEPARATOR_CHARS = set("();<>|&\n")
GIT_OPTIONS_WITH_VALUE = {
    "-C",
    "-c",
    "--git-dir",
    "--work-tree",
    "--namespace",
    "--config-env",
}
PUSH_OPTIONS_WITH_VALUE = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
PUSHES_ALL_BRANCHES = {"--all", "--branches", "--mirror"}
PREFIX_COMMANDS = {"env", "command", "time", "nohup", "sudo"}


def tokenize(command):
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace = " \t\r"
    lexer.wordchars += ":+@"
    return list(lexer)


def segments(tokens):
    segment = []
    for token in tokens:
        if set(token) <= SEPARATOR_CHARS:
            yield segment
            segment = []
        else:
            segment.append(token)
    yield segment


def git(cwd, *args):
    return subprocess.run(
        ["git", "-C", cwd, *args], check=False, capture_output=True, text=True
    )


def current_branch(cwd):
    return git(cwd, "symbolic-ref", "--short", "-q", "HEAD").stdout.strip()


def config(cwd, key):
    return git(cwd, "config", "--get", key).stdout.strip()


def push_remote(cwd):
    # The order git push itself uses when no remote is given.
    branch = current_branch(cwd)
    keys = ["remote.pushDefault"]
    if branch:
        keys = [f"branch.{branch}.pushRemote", *keys, f"branch.{branch}.remote"]
    return next((value for key in keys if (value := config(cwd, key))), "origin")


def remote_names(cwd):
    return git(cwd, "remote").stdout.split()


def normalized_url(url):
    return url.rstrip("/").removesuffix(".git")


def remote_urls(cwd, name):
    fetch, push = (
        git(cwd, "remote", "get-url", "--all", *flag, name).stdout.split()
        for flag in ([], ["--push"])
    )
    return {normalized_url(url) for url in [*fetch, *push]}


def remotes_for(repository, cwd):
    """The remotes a push to <repository>, a remote name, URL or path, goes to."""
    names = remote_names(cwd)
    if repository in names or not set(repository) & set(":/"):
        return [repository]
    url = normalized_url(repository)
    return [name for name in names if url in remote_urls(cwd, name)]


def protected_branches(cwd, remote):
    head = f"refs/remotes/{remote}/HEAD"
    ref = git(cwd, "symbolic-ref", "--quiet", head)
    target = ref.stdout.strip().removeprefix(f"refs/remotes/{remote}/")
    if ref.returncode != 0:
        return FALLBACK_BRANCHES
    if git(cwd, "rev-parse", "--verify", "--quiet", head).returncode != 0:
        return FALLBACK_BRANCHES | {target}
    return {target}


def destination(refspec, cwd):
    source, _, target = refspec.lstrip("+").partition(":")
    target = target or source
    if target in ("HEAD", "@"):
        target = current_branch(cwd)
    return target.removeprefix("refs/heads/")


def implicit_destinations(remote, cwd):
    """The branches a push to <remote> without refspec updates."""
    configured = git(cwd, "config", "--get-all", f"remote.{remote}.push").stdout
    if configured.split():
        return [destination(refspec, cwd) for refspec in configured.split()]
    branch = current_branch(cwd)
    mode = config(cwd, "push.default") or "simple"
    if mode == "matching":
        return [""]
    if mode in ("upstream", "tracking") and (
        config(cwd, f"branch.{branch}.remote") == remote
    ):
        upstream = config(cwd, f"branch.{branch}.merge").removeprefix("refs/heads/")
        return [branch, upstream] if upstream else [branch]
    return [branch]


def git_subcommand(args, cwd):
    while args and args[0].startswith("-"):
        option, has_value, value = args[0].partition("=")
        if option in GIT_OPTIONS_WITH_VALUE and not has_value:
            value = args[1] if len(args) > 1 else ""
            args = args[1:]
        if option == "-C":
            cwd = os.path.join(cwd, value)
        args = args[1:]
    return args, cwd


def pushes_to_default_branch(push_args, cwd):
    positional = []
    args = iter(push_args)
    for arg in args:
        if arg in PUSHES_ALL_BRANCHES:
            return True
        if arg in PUSH_OPTIONS_WITH_VALUE:
            next(args, None)
        elif not arg.startswith("-"):
            positional.append(arg)
    repository = positional[0] if positional else push_remote(cwd)
    remotes = remotes_for(repository, cwd)
    if remotes:
        protected = set().union(*(protected_branches(cwd, r) for r in remotes))
    else:
        # An unknown URL may be a remote spelled differently, e.g. SSH for HTTPS.
        protected = FALLBACK_BRANCHES.union(
            *(protected_branches(cwd, remote) for remote in remote_names(cwd))
        )
    refspecs = positional[1:]
    if refspecs:
        destinations = [destination(refspec, cwd) for refspec in refspecs]
    else:
        destinations = [
            target
            for remote in remotes or [repository]
            for target in implicit_destinations(remote, cwd)
        ]
    return any(targets(target, protected) for target in destinations)


def targets(target, protected):
    # An empty target is the matching refspec ":", a glob may expand to any branch.
    return target == "" or target in protected or "*" in target


def is_blocked(command, cwd):
    try:
        tokens = tokenize(command)
    except ValueError:
        return "git" in command and "push" in command
    for segment in segments(tokens):
        while segment and (
            segment[0] in PREFIX_COMMANDS
            or ("=" in segment[0] and not segment[0].startswith("-"))
        ):
            segment = segment[1:]
        if not segment:
            continue
        if segment[0] == "cd" and len(segment) > 1:
            cwd = os.path.join(cwd, segment[1])
        elif os.path.basename(segment[0]) == "git":
            args, git_cwd = git_subcommand(segment[1:], cwd)
            if args[:1] == ["push"] and pushes_to_default_branch(args[1:], git_cwd):
                return True
    return False


def main():
    hook_input = json.load(sys.stdin)
    command = hook_input.get("tool_input", {}).get("command", "")
    if is_blocked(command, hook_input.get("cwd", os.getcwd())):
        print(
            "Pushing to the default branch is not allowed; open a pull request. "
            "Without <remote>/HEAD, main and master are protected; to set it, run: "
            "git remote set-head <remote> --auto",
            file=sys.stderr,
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
