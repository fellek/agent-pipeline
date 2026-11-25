#!/usr/bin/env python3
"""`gh` of the autopilot user (installed as ~/.local/bin/gh): gh through the gate.

The gate cannot read the user's files, so it takes a body only on stdin. A Bash
call with a heredoc or redirect stays in the sandbox, where sudo cannot run. So a
fork writes the text to a file in a sandboxed call, and runs gh with the file's
path outside the sandbox; this passes the file as stdin.
"""

import os
import sys

GATE = ["sudo", "-n", "-u", "pipeline-gate", "/opt/pipeline/gate", "gh"]


def file_flags(args):
    # In `gh api`, -F is a field, not a file.
    return {"--input"} if args[:1] == ["api"] else {"-F", "--body-file", "--input"}


def convert(args):
    """The arguments with a file path replaced by `-`, and that path."""
    flags = file_flags(args)
    out, path, i = [], None, 0
    while i < len(args):
        name, eq, inline = args[i].partition("=")
        value = inline if eq else (args[i + 1] if i + 1 < len(args) else "-")
        if name in flags and value != "-":
            if path is not None:
                sys.exit("gh: only one file flag through the gate")
            path = value
            out += [name, "-"]
            i += 1 if eq else 2
            continue
        out.append(args[i])
        i += 1
    return out, path


def main(argv):
    args, path = convert(argv)
    if path is not None:
        fd = os.open(path, os.O_RDONLY)
        os.dup2(fd, 0)
        os.close(fd)
    os.execvp(GATE[0], GATE + args)


if __name__ == "__main__":
    main(sys.argv[1:])
