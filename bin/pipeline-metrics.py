#!/usr/bin/env python3
"""Record the metrics of the merged or parked issue in the pipeline log, or
summarize them.

Usage:
  pipeline-metrics.py record
  pipeline-metrics.py park <reason>
  pipeline-metrics.py summary
"""

import json
import statistics
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

MARKER = "merge metrics"
PARK_MARKER = "park metrics"


def pipeline_dir():
    """State of the project root, not of the plugin, also from a subdirectory."""
    root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    return Path(root or ".") / ".pipeline"


def gh_api(*args):
    return subprocess.run(
        ["gh", "api", *args], capture_output=True, text=True, check=True
    ).stdout


def gh(path):
    pages = json.loads(gh_api("--paginate", "--slurp", path))
    return [item for page in pages for item in page]


def last_labeled_at(events, label):
    times = [
        e["created_at"]
        for e in events
        if e["event"] == "labeled" and e["label"]["name"] == label
    ]
    return max(times, default=None)


def metrics_line(state, merged_at, labeled_at):
    duration = None
    if labeled_at:
        elapsed = datetime.fromisoformat(merged_at) - datetime.fromisoformat(labeled_at)
        duration = int(elapsed.total_seconds())
    metrics = {
        "issue": state["issue"],
        "pr": state["pr"],
        "review_rounds": state["review_rounds"],
        "attempts": state.get("attempts_per_step", {}),
        "questions": state.get("questions", 0),
        "duration_s": duration,
        "usage": state.get("usage", {}),
    }
    return f"{merged_at} #{state['issue']} {MARKER} {json.dumps(metrics)}"


def park_line(state, reason, at):
    metrics = {
        "issue": state["issue"],
        "reason": reason,
        "review_rounds": state["review_rounds"],
        "attempts": state.get("attempts_per_step", {}),
        "questions": state.get("questions", 0),
        "usage": state.get("usage", {}),
    }
    return f"{at} #{state['issue']} {PARK_MARKER} {json.dumps(metrics)}"


def park(state_path, log_path, reason):
    state = json.loads(state_path.read_text())
    at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    with log_path.open("a") as log:
        log.write(park_line(state, reason, at) + "\n")


def record(state_path, log_path):
    state = json.loads(state_path.read_text())
    repo = "repos/{owner}/{repo}"
    merged_at = json.loads(gh_api(f"{repo}/pulls/{state['pr']}"))["merged_at"]
    events = gh(f"{repo}/issues/{state['issue']}/events?per_page=100")
    labeled_at = last_labeled_at(events, state.get("label", "ready"))
    with log_path.open("a") as log:
        log.write(metrics_line(state, merged_at, labeled_at) + "\n")


def read_metrics(log_path):
    """The merge records, then the park records."""
    if not log_path.exists():
        return [], []
    merged, parked = [], []
    for line in log_path.read_text().splitlines():
        parts = line.split(" ", 4)
        marker = " ".join(parts[2:4]) if len(parts) == 5 else None
        if marker == MARKER:
            merged.append(json.loads(parts[4]))
        elif marker == PARK_MARKER:
            parked.append(json.loads(parts[4]))
    return merged, parked


def hours(seconds):
    return f"{seconds / 3600:.1f} h"


def summarize(merged, parked=()):
    lines = merge_summary(merged) if merged else ["0 Issues"]
    if parked:
        reasons = {}
        for record in parked:
            reasons[record["reason"]] = reasons.get(record["reason"], 0) + 1
        listed = ", ".join(
            f"{reason} {count}" for reason, count in sorted(reasons.items())
        )
        lines.append(f"Parks: {len(parked)} ({listed})")
    # Usage grows over park and resume, so only the latest record of an issue counts.
    latest = {r["issue"]: r for r in [*parked, *merged]}
    usages = [r["usage"] for r in latest.values() if r.get("usage")]
    for step in sorted({step for usage in usages for step in usage}):
        tokens = [usage[step]["tokens"] for usage in usages if step in usage]
        lines.append(f"Tokens {step}: Mittel {statistics.mean(tokens):.0f} je Issue")
    return "\n".join(lines)


def merge_summary(records):
    rounds = [r["review_rounds"] for r in records]
    lines = [
        f"{len(records)} Issues",
        f"Review-Runden: Mittel {statistics.mean(rounds):.1f}, Max {max(rounds)}",
    ]
    steps = sorted({step for r in records for step in r["attempts"]})
    for step in steps:
        counts = [r["attempts"][step] for r in records if step in r["attempts"]]
        lines.append(f"Versuche {step}: Mittel {statistics.mean(counts):.1f}")
    lines.append(f"Rückfragen: {sum(r['questions'] for r in records)}")
    durations = [r["duration_s"] for r in records if r["duration_s"] is not None]
    if durations:
        median = hours(statistics.median(durations))
        lines.append(f"Dauer: Median {median}, Max {hours(max(durations))}")
    return lines


def main(argv):
    match argv:
        case ["record"]:
            pipeline = pipeline_dir()
            record(pipeline / "state.json", pipeline / "autopilot.log")
        case ["park", reason]:
            pipeline = pipeline_dir()
            park(pipeline / "state.json", pipeline / "autopilot.log", reason)
        case ["summary"]:
            print(summarize(*read_metrics(pipeline_dir() / "autopilot.log")))
        case _:
            sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
