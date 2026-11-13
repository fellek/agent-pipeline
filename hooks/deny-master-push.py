#!/usr/bin/env python3
"""PreToolUse hook: blocks Bash commands that push to master (exit 2)."""

import json
import os
import shlex
import subprocess
import sys

PROTECTED = "master"
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
    lexer.wordchars += ":+"
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


def current_branch(cwd):
    result = subprocess.run(
        ["git", "-C", cwd, "symbolic-ref", "--short", "-q", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def destination(refspec, cwd):
    source, _, target = refspec.lstrip("+").partition(":")
    target = target or source
    if target == "HEAD":
        target = current_branch(cwd)
    return target.removeprefix("refs/heads/")


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


def pushes_to_master(push_args, cwd):
    positional = []
    args = iter(push_args)
    for arg in args:
        if arg in PUSHES_ALL_BRANCHES:
            return True
        if arg in PUSH_OPTIONS_WITH_VALUE:
            next(args, None)
        elif not arg.startswith("-"):
            positional.append(arg)
    refspecs = positional[1:]
    if not refspecs:
        return current_branch(cwd) == PROTECTED
    return any(targets_master(destination(refspec, cwd)) for refspec in refspecs)


def targets_master(target):
    # An empty target is the matching refspec ":", a glob may expand to master.
    return target in ("", PROTECTED) or "*" in target


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
            if args[:1] == ["push"] and pushes_to_master(args[1:], git_cwd):
                return True
    return False


def main():
    hook_input = json.load(sys.stdin)
    command = hook_input.get("tool_input", {}).get("command", "")
    if is_blocked(command, hook_input.get("cwd", os.getcwd())):
        print(
            f"Pushing to {PROTECTED} is not allowed; open a pull request.",
            file=sys.stderr,
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
