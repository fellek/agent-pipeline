#!/usr/bin/env python3
"""Run a background command of the orchestrator and keep its result.

The orchestrator starts it with run_in_background and reports only its end to
autopilot-state.py, which reads the result from .pipeline/tasks/: <name>.out
(stdout and stderr) and <name>.exit. While it runs, <name>.pid lets
autopilot-state.py stop it, e.g. the poller before the autopilot posts on GitHub.

Usage:
  autopilot-task.py <name> <command> [<arg>...]
"""

import os
import signal
import subprocess
import sys
from pathlib import Path


def tasks_dir():
    """Of the project root, not of the plugin, also from a subdirectory."""
    root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    return Path(root or ".") / ".pipeline" / "tasks"


def main(argv):
    if len(argv) < 2 or "/" in argv[0]:
        sys.exit(__doc__)
    name, command = argv[0], argv[1:]
    folder = tasks_dir()
    folder.mkdir(parents=True, exist_ok=True)
    for suffix in (".out", ".exit"):
        (folder / f"{name}{suffix}").unlink(missing_ok=True)
    pid = folder / f"{name}.pid"
    with (folder / f"{name}.out").open("w") as out:
        child = subprocess.Popen(command, stdout=out, stderr=subprocess.STDOUT)
        pid.write_text(f"{os.getpid()}\n")

        def stop(signum, frame):
            child.terminate()

        signal.signal(signal.SIGTERM, stop)
        code = child.wait()
    pid.unlink(missing_ok=True)
    (folder / f"{name}.exit").write_text(f"{code}\n")
    sys.exit(code)


if __name__ == "__main__":
    main(sys.argv[1:])
