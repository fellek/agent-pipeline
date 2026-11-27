#!/usr/bin/env python3
"""PreToolUse hook: blocks a Bash call that would reach GitHub from inside the
sandbox (exit 2).

git push, fetch and pull, gh and gate reach GitHub only through the gate, which they
call with sudo. The sandbox sets "no new privileges", so sudo fails there, and
Claude Code runs a call outside it only if every command matches an excludedCommands
entry and the call has no cd, redirect, heredoc or substitution. So such a call has
to be one command that starts with the command itself. Commands are found with the
shell parsing of deny-default-branch-push.py; heredoc bodies are text, not commands.
The hook guards against mistakes: a call through sh -c, eval or a script is not seen.
"""

import importlib.util
import json
import os
import re
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "deny_default_branch_push", Path(__file__).with_name("deny-default-branch-push.py")
)
shell = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shell)

GITHUB_GIT = {"push", "fetch", "pull"}
GITHUB_COMMANDS = {"gh", "gate"}
SANDBOXING_CHARS = ("$", "`", "\n")
HEREDOC = re.compile(r"<<(-?)\s*(['\"]?)([\w.-]+)\2")
MESSAGE = (
    "This call would run in the Bash sandbox, where git push, fetch and pull, gh and "
    "gate cannot reach GitHub (sudo to the gate is blocked there). Run it as a call "
    "of its own that starts with the command itself, e.g. "
    "`git push -u origin <branch>` or `gh pr create --head <branch> --body-file "
    ".pipeline/body.md`: no cd, git -C, variable assignment, redirect (also 2>&1), "
    "pipe, chain, heredoc, `$` or backticks."
)


def without_heredoc_bodies(command):
    lines = []
    delimiters = []
    for line in command.split("\n"):
        if delimiters:
            strip_tabs, delimiter = delimiters[0]
            if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                delimiters.pop(0)
            continue
        lines.append(line)
        delimiters = [(dash == "-", word) for dash, _, word in HEREDOC.findall(line)]
    return "\n".join(lines)


def reaches_github(segment):
    segment, _ = shell.strip_prefixes(segment, {}, "")
    if not segment:
        return False
    name = os.path.basename(segment[0])
    if name == "git":
        args, _ = shell.git_subcommand(segment[1:], shell.Repo(""))
        return bool(args) and args[0] in GITHUB_GIT
    return name in GITHUB_COMMANDS


def is_plain(command, tokens):
    if any(char in command for char in SANDBOXING_CHARS):
        return False
    if any(token and set(token) <= shell.SEPARATOR_CHARS for token in tokens):
        return False
    if tokens[0] == "git":
        return len(tokens) > 1 and tokens[1] in GITHUB_GIT
    return tokens[0] in GITHUB_COMMANDS


def is_blocked(command):
    try:
        tokens = shell.tokenize(without_heredoc_bodies(command))
    except ValueError:
        return False
    if not any(reaches_github(segment) for segment in shell.segments(tokens)):
        return False
    return not is_plain(command, tokens)


def main():
    command = json.load(sys.stdin).get("tool_input", {}).get("command", "")
    if is_blocked(command):
        print(MESSAGE, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
