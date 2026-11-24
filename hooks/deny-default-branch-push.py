#!/usr/bin/env python3
"""PreToolUse hook: blocks Bash commands that push to the default branch (exit 2).

The default branch is read locally, without a network call, from
refs/remotes/<remote>/HEAD of the remote pushed to, in the repository the push runs
in. If that ref is not set or points to a deleted branch, main, master and the
deleted branch are protected. A URL or path is matched against the URLs of the
configured remotes; if none matches, the default branches of all remotes are
protected. Without a remote, the push remote comes from the git config, and
without a refspec, the destination follows remote.<remote>.push and push.default;
a refspec without :<dst> is also mapped through remote.<remote>.push, as git does.
-c, --config-env and variable assignments before git count like the repository's
config. If a push would update the current branch and that branch is unknown, e.g.
after a cd the hook cannot follow, the push is blocked with its own message.

Pushes are found behind shell keywords and groups, prefix commands such as env and
sudo, command substitutions (also in double quotes), sh -c, eval and git aliases.
The hook guards against mistakes, not against a determined user: a push in a script
file, through a function or a variable set in the same command is not seen.
"""

import json
import os
import re
import shlex
import subprocess
import sys
from typing import NamedTuple

FALLBACK_BRANCHES = {"main", "master"}
SEPARATOR_CHARS = set("();<>|&\n`")
# Global git options that change which repository or config a command sees.
GIT_OPTIONS_WITH_VALUE = {
    "-C",
    "-c",
    "--git-dir",
    "--work-tree",
    "--namespace",
    "--config-env",
    "--exec-path",
}
PASSED_GIT_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--config-env", "--bare"}
PUSH_OPTIONS_WITH_VALUE = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
PUSHES_ALL_BRANCHES = {"--all", "--branches", "--mirror"}
# Words that may come before a command, with their options that take a value.
PREFIX_COMMANDS = {
    "env": {"-u", "-C", "--unset", "--chdir"},
    "sudo": {"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U"},
    "command": set(),
    "time": set(),
    "nohup": set(),
    "exec": {"-a"},
    "builtin": set(),
}
SHELL_KEYWORDS = {"{", "}", "!", "if", "then", "else", "elif", "while", "until", "do"}
SHELLS = {"sh", "bash", "dash", "zsh", "ksh"}
# Command substitutions, also inside double quotes, where shlex keeps them in a word.
SUBSTITUTION = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")
MAX_DEPTH = 5
DEFAULT_BRANCH = (
    "Pushing to the default branch is not allowed; open a pull request. "
    "Without <remote>/HEAD, main and master are protected; to set it, run: "
    "git remote set-head <remote> --auto"
)
UNKNOWN_BRANCH = (
    "Cannot tell which branch this push updates: there is no current branch in {cwd} "
    "(detached HEAD, or a directory the hook cannot follow). "
    "Name the branch, e.g. git push origin <branch>."
)


class Repo(NamedTuple):
    """Where a git command runs: the shell's directory, git's global options that
    select repository and config (-C, -c, --git-dir, ...), and the environment."""

    cwd: str
    options: tuple = ()
    env: dict | None = None

    @property
    def where(self):
        path = self.cwd
        for option, value in zip(self.options, self.options[1:]):
            if option == "-C":
                path = os.path.join(path, value)
        return path

    def git(self, *args):
        return subprocess.run(
            ["git", "-C", self.cwd, *self.options, *args],
            check=False,
            capture_output=True,
            text=True,
            env=self.env,
        )


def tokenize(command):
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace = " \t\r"
    # "$" and braces keep $VAR and ${VAR} in one word, for resolve().
    lexer.wordchars += ":+@${}"
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


def current_branch(repo):
    return repo.git("symbolic-ref", "--short", "-q", "HEAD").stdout.strip()


def config(repo, key):
    return repo.git("config", "--get", key).stdout.strip()


def push_remote(repo):
    # The order git push itself uses when no remote is given.
    branch = current_branch(repo)
    keys = ["remote.pushDefault"]
    if branch:
        keys = [f"branch.{branch}.pushRemote", *keys, f"branch.{branch}.remote"]
    return next((value for key in keys if (value := config(repo, key))), "origin")


def remote_names(repo):
    return repo.git("remote").stdout.split()


def normalized_url(url):
    return url.rstrip("/").removesuffix(".git")


def remote_urls(repo, name):
    fetch, push = (
        repo.git("remote", "get-url", "--all", *flag, name).stdout.split()
        for flag in ([], ["--push"])
    )
    return {normalized_url(url) for url in [*fetch, *push]}


def remotes_for(repository, repo):
    """The remotes a push to <repository>, a remote name, URL or path, goes to."""
    names = remote_names(repo)
    if repository in names or not set(repository) & set(":/"):
        return [repository]
    url = normalized_url(repository)
    return [name for name in names if url in remote_urls(repo, name)]


def protected_branches(repo, remote):
    head = f"refs/remotes/{remote}/HEAD"
    ref = repo.git("symbolic-ref", "--quiet", head)
    target = ref.stdout.strip().removeprefix(f"refs/remotes/{remote}/")
    if ref.returncode != 0:
        return FALLBACK_BRANCHES
    if repo.git("rev-parse", "--verify", "--quiet", head).returncode != 0:
        return FALLBACK_BRANCHES | {target}
    return {target}


def full_ref(name, repo):
    """refs/heads/<branch> for a branch name, HEAD or @; None for an unknown branch."""
    if name in ("HEAD", "@"):
        name = current_branch(repo)
        if not name:
            return None
    return name if name.startswith("refs/") else f"refs/heads/{name}"


def configured_push(remote, repo):
    return repo.git("config", "--get-all", f"remote.{remote}.push").stdout.split()


def destination(refspec, repo):
    """The branch <refspec> updates; None if that is the unknown current branch."""
    source, _, target = refspec.lstrip("+").partition(":")
    target = target or source
    if target == "":
        return ""
    ref = full_ref(target, repo)
    return ref and ref.removeprefix("refs/heads/")


def mapped_destinations(source, remote, repo):
    """Where remote.<remote>.push sends <source> given without :<dst>. As in git, only
    configured sources written as full refs match, so HEAD:<dst> does not."""
    ref = full_ref(source.lstrip("+"), repo)
    for spec in configured_push(remote, repo):
        spec_source, _, spec_target = spec.lstrip("+").partition(":")
        spec_target = spec_target or spec_source
        prefix, glob, suffix = spec_source.partition("*")
        if not ref or not spec_source.startswith("refs/"):
            continue
        if glob and ref.startswith(prefix) and ref.endswith(suffix):
            name = ref[len(prefix) : len(ref) - len(suffix)]
            yield destination(spec_target.replace("*", name, 1), repo)
        elif spec_source == ref:
            yield destination(spec_target, repo)


def explicit_destinations(refspecs, remote, repo):
    """The branches a push of <refspecs> to <remote> updates."""
    for refspec in refspecs:
        yield destination(refspec, repo)
        if ":" not in refspec:
            yield from mapped_destinations(refspec, remote, repo)


def implicit_destinations(remote, repo):
    """The branches a push to <remote> without refspec updates."""
    configured = configured_push(remote, repo)
    if configured:
        return [destination(refspec, repo) for refspec in configured]
    branch = current_branch(repo)
    mode = config(repo, "push.default") or "simple"
    if mode == "matching":
        return [""]
    if not branch:
        return [None]
    if mode in ("upstream", "tracking") and (
        config(repo, f"branch.{branch}.remote") == remote
    ):
        upstream = config(repo, f"branch.{branch}.merge").removeprefix("refs/heads/")
        return [branch, upstream] if upstream else [branch]
    return [branch]


def resolve(cwd, path):
    # Expands what the shell would, as far as the hook's environment knows it.
    return os.path.join(cwd, os.path.expandvars(os.path.expanduser(path)))


def git_subcommand(args, repo):
    """The git subcommand with its arguments, and the repository it runs in."""
    options = []
    while args and args[0].startswith("-"):
        option, has_value, value = args[0].partition("=")
        if option in GIT_OPTIONS_WITH_VALUE and not has_value:
            value = args[1] if len(args) > 1 else ""
            args = args[1:]
        if option in ("-C", "--git-dir", "--work-tree"):
            value = os.path.expandvars(os.path.expanduser(value))
        if option in PASSED_GIT_OPTIONS:
            options += [option, value] if option in GIT_OPTIONS_WITH_VALUE else [option]
        args = args[1:]
    return args, repo._replace(options=tuple(options))


def blocked_push(push_args, repo):
    """The reason to block `git push <push_args>` in <repo>, or None."""
    positional = []
    repo_option = None
    args = iter(push_args)
    for arg in args:
        option, has_value, value = arg.partition("=")
        if arg in PUSHES_ALL_BRANCHES:
            return DEFAULT_BRANCH
        if option == "--repo":
            repo_option = value if has_value else next(args, None)
        elif arg in PUSH_OPTIONS_WITH_VALUE:
            next(args, None)
        elif not arg.startswith("-"):
            positional.append(arg)
    # As in git, a repository argument takes precedence over --repo.
    repository = positional[0] if positional else repo_option or push_remote(repo)
    remotes = remotes_for(repository, repo)
    if remotes:
        protected = set().union(*(protected_branches(repo, r) for r in remotes))
    else:
        # An unknown URL may be a remote spelled differently, e.g. SSH for HTTPS.
        protected = FALLBACK_BRANCHES.union(
            *(protected_branches(repo, remote) for remote in remote_names(repo))
        )
    refspecs = positional[1:]
    destinations = [
        target
        for remote in remotes or [repository]
        for target in (
            explicit_destinations(refspecs, remote, repo)
            if refspecs
            else implicit_destinations(remote, repo)
        )
    ]
    if None in destinations:
        return UNKNOWN_BRANCH.format(cwd=repo.where)
    if any(targets(target, protected) for target in destinations):
        return DEFAULT_BRANCH
    return None


def targets(target, protected):
    # An empty target is the matching refspec ":", a glob may expand to any branch.
    return target == "" or target in protected or "*" in target


def strip_prefixes(segment, env):
    """<segment> without leading prefix commands, their options, shell keywords and
    variable assignments; the assignments go into <env>."""
    while segment:
        word = segment[0]
        if word in PREFIX_COMMANDS or word in SHELL_KEYWORDS:
            segment = segment[1:]
            options = PREFIX_COMMANDS.get(word, set())
            while segment and segment[0].startswith("-") and word in PREFIX_COMMANDS:
                takes_value = segment[0] in options
                segment = segment[2:] if takes_value else segment[1:]
        elif "=" in word and not word.startswith("-"):
            name, _, value = word.partition("=")
            env[name] = value
            segment = segment[1:]
        else:
            break
    return segment


def is_blocked(command, cwd, depth=0):
    """The reason to block <command> run in <cwd>, or None."""
    if depth > MAX_DEPTH:
        return DEFAULT_BRANCH if "push" in command else None
    for match in SUBSTITUTION.finditer(command):
        inner = match.group(1) if match.group(1) is not None else match.group(2)
        if reason := is_blocked(inner, cwd, depth + 1):
            return reason
    try:
        tokens = tokenize(command)
    except ValueError:
        return DEFAULT_BRANCH if "git" in command and "push" in command else None
    for segment in segments(tokens):
        env = {}
        segment = strip_prefixes(segment, env)
        if not segment:
            continue
        name = os.path.basename(segment[0])
        if name in ("cd", "pushd") and len(segment) > 1:
            cwd = resolve(cwd, segment[1])
        elif name in SHELLS and "-c" in segment[1:-1]:
            script = segment[segment.index("-c", 1) + 1]
            if reason := is_blocked(script, cwd, depth + 1):
                return reason
        elif name == "eval":
            if reason := is_blocked(" ".join(segment[1:]), cwd, depth + 1):
                return reason
        elif name == "git":
            repo = Repo(cwd, env={**os.environ, **env} if env else None)
            if reason := blocked_git(segment[1:], repo, depth):
                return reason
    return None


def blocked_git(git_args, repo, depth):
    args, repo = git_subcommand(git_args, repo)
    if not args:
        return None
    if args[0] == "push":
        return blocked_push(args[1:], repo)
    # An alias may stand for push, or for a shell command that pushes.
    alias = config(repo, f"alias.{args[0]}")
    if not alias or depth >= MAX_DEPTH:
        return None
    rest = " ".join(shlex.quote(arg) for arg in args[1:])
    if alias.startswith("!"):
        return is_blocked(f"{alias[1:]} {rest}", repo.where, depth + 1)
    try:
        expanded = shlex.split(alias)
    except ValueError:
        return DEFAULT_BRANCH if "push" in alias else None
    return blocked_git([*repo.options, *expanded, *args[1:]], repo, depth + 1)


def main():
    hook_input = json.load(sys.stdin)
    command = hook_input.get("tool_input", {}).get("command", "")
    if reason := is_blocked(command, hook_input.get("cwd", os.getcwd())):
        print(reason, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
