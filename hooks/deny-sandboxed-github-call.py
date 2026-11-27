#!/usr/bin/env python3
"""PreToolUse hook: blocks a Bash call that would reach GitHub from inside the
sandbox (exit 2).

git push, fetch and pull, gh and gate reach GitHub only through the gate, which they
call with sudo. The sandbox sets "no new privileges", so sudo fails there, and
Claude Code runs a call outside it only if every command matches an excludedCommands
entry and the call has no cd, redirect, heredoc or substitution. So such a call has
to be one command that starts with the command itself. The hook guards against
mistakes: a call through sh -c, eval or a script is not seen.
"""

import json
import os
import shlex
import sys

GITHUB_GIT = {"push", "fetch", "pull"}
GITHUB_COMMANDS = {"gh", "gate"}
GIT_OPTIONS_WITH_VALUE = {
    "-C",
    "-c",
    "--git-dir",
    "--work-tree",
    "--namespace",
    "--config-env",
}
PREFIX_COMMANDS = {"env", "command", "sudo", "nohup", "time", "timeout", "exec", "nice"}
SEPARATOR_CHARS = set("();<>|&\n")
SANDBOXING_CHARS = ("$", "`", "\n")
MESSAGE = (
    "This call would run in the Bash sandbox, where git push, fetch and pull, gh and "
    "gate cannot reach GitHub (sudo to the gate is blocked there). Run it as a call "
    "of its own that starts with the command itself, e.g. "
    "`git push -u origin <branch>` or `gh pr create --head <branch> --body-file "
    ".pipeline/body.md`: no cd, git -C, variable assignment, redirect (also 2>&1), "
    "pipe, chain, heredoc, `$` or backticks."
)


def tokenize(command):
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace = " \t\r"
    return list(lexer)


def segments(tokens):
    segment = []
    for token in tokens:
        if token and set(token) <= SEPARATOR_CHARS:
            yield segment
            segment = []
        else:
            segment.append(token)
    yield segment


def strip_prefixes(segment):
    """<segment> without leading variable assignments and prefix commands with their
    options."""
    prefixed = False
    while segment:
        word = segment[0]
        if word in PREFIX_COMMANDS:
            prefixed = True
        elif not (
            ("=" in word and not word.startswith("-"))
            or prefixed
            and word[0] in "-0123456789"
        ):
            break
        segment = segment[1:]
    return segment


def git_subcommand(args):
    args = iter(args)
    for arg in args:
        if arg in GIT_OPTIONS_WITH_VALUE:
            next(args, None)
        elif not arg.startswith("-"):
            return arg
    return None


def reaches_github(segment):
    segment = strip_prefixes(segment)
    if not segment:
        return False
    name = os.path.basename(segment[0])
    if name == "git":
        return git_subcommand(segment[1:]) in GITHUB_GIT
    return name in GITHUB_COMMANDS


def is_plain(command, tokens):
    if any(char in command for char in SANDBOXING_CHARS):
        return False
    if any(token and set(token) <= SEPARATOR_CHARS for token in tokens):
        return False
    if tokens[0] == "git":
        return len(tokens) > 1 and tokens[1] in GITHUB_GIT
    return tokens[0] in GITHUB_COMMANDS


def is_blocked(command):
    try:
        tokens = tokenize(command)
    except ValueError:
        return False
    if not any(reaches_github(segment) for segment in segments(tokens)):
        return False
    return not is_plain(command, tokens)


def main():
    command = json.load(sys.stdin).get("tool_input", {}).get("command", "")
    if is_blocked(command):
        print(MESSAGE, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
