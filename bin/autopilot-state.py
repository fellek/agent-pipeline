#!/usr/bin/env python3
"""State machine of the autopilot orchestrator.

The orchestrator skill reports every event here and executes the actions this
prints; the transitions, the state in .pipeline/state.json and the log
.pipeline/autopilot.log live only here. Shell commands, GitHub calls and
Telegram messages run here as well, so the model only starts forks and
background tasks and stops them.

Events:
  start [<label>]        the skill was invoked (default label: ready)
  telegram <chat_id>     a message of the maintainer, its text on stdin
  started <task_id>      the fork or background task of the last action started
  done <task_id>         a fork or background task ended; a fork's result on stdin

Actions, one JSON object per line:
  {"skill": <name>, "args": <args>}   run the skill via the Skill tool, then `started`
  {"background": <command>, "timeout": <ms>}
                                      run it as background Bash with that timeout,
                                      then `started`
  {"stop": <task_id>}                 stop the task with TaskStop
  {"reply": <text>}                   send the text with the reply tool of Telegram

Usage:
  autopilot-state.py event <event> [<arg>...]
"""

import json
import os
import re
import signal
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


def pipeline_dir():
    """State of the project root, not of the plugin, also from a subdirectory."""
    root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    return Path(root or ".") / ".pipeline"


PIPELINE = pipeline_dir()
PLUGIN = Path(__file__).resolve().parents[1]
MAX_ATTEMPTS = 3
REVIEW_INFO_ROUNDS = 3
REVIEW_LIMIT_ROUNDS = 5
MAX_POLL_FAILURES = 3
STATUS_LABELS = ["ready", "in-progress", "in-review", "approved", "question", "parked"]
STEP_LABELS = {
    "plan-issue": "in-progress",
    "issue": "in-progress",
    "fix-review": "in-progress",
    "review-issue": "in-review",
}
TASKS = ("plan-issue", "issue", "review-issue", "fix-review")
CLEAN_STEPS = ("plan-issue", "review-issue", "setprio")
ISSUE_FIELDS = {
    "issue": None,
    "branch": None,
    "pr": None,
    "step": None,
    "attempts": 0,
    "review_rounds": 0,
    "waiting_for": None,
    "question": None,
    "events_since": None,
    "attempts_per_step": {},
    "questions": 0,
    "failure": None,
    "task_id": None,
    "park": None,
    "head": None,
    "merge": None,
}
DEFAULT = {
    "chat_id": None,
    **ISSUE_FIELDS,
    "paused": False,
    "verbose": False,
    "label": "ready",
    "parked": [],
    "poller": None,
    "poll_failures": 0,
    "pending": None,
}
# Fields a parked entry keeps of the state.
PARKED_FIELDS = (
    "issue",
    "branch",
    "pr",
    "step",
    "review_rounds",
    "attempts_per_step",
    "questions",
    "events_since",
    "question",
)
RUNNING = ("step", "ci", "merge_ci")
# The longest background call: two CI waits of 45 minutes each.
BACKGROUND_MS = 7_200_000
DIRTY = "Ungesicherte Änderungen im Arbeitsbaum, cleanup sichert sie auf einem Branch"
PAUSED = "Pausiert, weiter setzt fort"
COMMAND = re.compile(
    r"^(?:#(?P<answer>\d+)\s+(?P<text>.+)"
    r"|(?P<simple>help|status|pause|weiter|cleanup|update|/verbose)"
    r"|(?P<park>park|stop)\s+#(?P<park_n>\d+)"
    r"|label\s+(?P<label>\S+)"
    r"|/(?P<task>[\w-]+)(?:\s+(?P<task_n>\d+))?)$",
    re.DOTALL,
)


class Wait(Exception):
    """Ends the handling of an event: the state is written and the turn ends."""


def now():
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_result(text):
    """The fields of the last result block in the text, or None."""
    start = (text or "").rfind("STATUS:")
    if start < 0:
        return None
    fields, key = {}, None
    for line in text[start:].splitlines():
        match = re.match(r"^([A-Z_]+):\s?(.*)$", line)
        if match and match.group(1) in (
            "STATUS",
            "SUMMARY",
            "VERDICT",
            "OPEN_QUESTIONS",
            "PATCH",
            "PIPELINE_FINDING",
            "NEXT",
        ):
            key = match.group(1)
            fields[key] = match.group(2).strip()
        elif key == "OPEN_QUESTIONS":
            fields[key] = (fields[key] + "\n" + line).strip()
    fields["STATUS"] = (
        fields.get("STATUS", "").split()[0] if fields.get("STATUS") else ""
    )
    return fields


def numbered(question):
    return re.findall(r"(?m)^\s*\d+\.\s*(.*)$", question or "")


def options(question):
    return re.findall(r"\b([a-z])\)", question or "")


def expand(answer, question):
    """An answer of a bare option letter or `Empfehlungen`, with its context."""
    if re.fullmatch(r"[a-z]", answer):
        match = re.search(
            rf"\b{answer}\)\s*(.*?)(?=\s+[a-z]\)|\s+Recommendation:|$)",
            question or "",
            re.DOTALL,
        )
        if match:
            return f"{answer}) {match.group(1).strip()}"
    if answer == "Empfehlungen":
        recommendations = [
            match.group(1).strip()
            for item in numbered(question)
            if (match := re.search(r"Recommendation:\s*(.*)$", item))
        ]
        return "Empfehlungen übernehmen: " + " ".join(
            f"{i}. {r}" for i, r in enumerate(recommendations, 1)
        )
    return answer


def help_text():
    text = (PLUGIN / "docs" / "autopilot.md").read_text()
    section = re.search(
        r"^## Telegram-Befehle\n(.*?)(?=^## |\Z)", text, re.DOTALL | re.MULTILINE
    ).group(1)
    lines = [line for line in section.strip().splitlines()[1:] if line.strip()]
    return "\n".join(line.replace("`", "") for line in lines)


def slug(title):
    words = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-").split("-")
    return "-".join(words[:5]) or "issue"


class Autopilot:
    def __init__(self, state):
        self.s = {**DEFAULT, **json.loads(json.dumps(state))}
        self.before = json.loads(json.dumps(self.s))
        self.actions = []

    # environment

    def run(self, *args, input=None):
        """Run a command; returns (exit code, stdout, stderr)."""
        # telegram-send.py and pipeline-metrics.py read the state.
        self.save()
        result = subprocess.run(
            list(args), input=input, capture_output=True, text=True, check=False
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()

    def ok(self, *args, input=None):
        code, out, err = self.run(*args, input=input)
        if code != 0:
            raise RuntimeError(err or out or f"{args[0]} failed")
        return out

    def task_file(self, name, suffix):
        path = PIPELINE / "tasks" / f"{name}{suffix}"
        return path.read_text().strip() if path.exists() else None

    def stop_poller(self):
        pid = self.task_file("poller", ".pid")
        if pid:
            try:
                os.kill(int(pid), signal.SIGTERM)
            except (ProcessLookupError, ValueError):
                pass
        self.s["poller"] = None

    # output

    def act(self, **action):
        self.actions.append(action)

    def send(self, text, *buttons):
        code, _, _ = self.run("telegram-send.py", *buttons, input=text)
        if code != 0 and buttons:
            code, _, _ = self.run("telegram-send.py", input=text)
        if code != 0:
            self.act(reply=text)

    def log(self, event):
        issue = self.s["issue"]
        line = f"#{issue} {self.s['step']} {event}" if issue else event
        PIPELINE.mkdir(parents=True, exist_ok=True)
        with (PIPELINE / "autopilot.log").open("a") as log:
            log.write(f"{now()} {line}\n")
        if self.s["verbose"]:
            self.send(line)

    def wait(self):
        raise Wait

    def pause(self):
        self.s["paused"] = True
        if self.s["waiting_for"] is None:
            self.s["waiting_for"] = "resume"
        self.wait()

    # GitHub

    def set_label(self, issue, label):
        others = [name for name in STATUS_LABELS if name != label]
        args = ["gh", "issue", "edit", str(issue), "--remove-label", ",".join(others)]
        if label:
            args += ["--add-label", label]
        self.run(*args)

    def comment(self, issue, body):
        self.run("gh", "issue", "comment", str(issue), "--body-file", "-", input=body)

    def default_branch(self):
        return self.ok("default-branch.py")

    def head_sha(self):
        return self.ok(
            "gh",
            "pr",
            "view",
            str(self.s["pr"]),
            "--json",
            "headRefOid",
            "--jq",
            ".headRefOid",
        )

    def github_now(self):
        return self.ok("autopilot-poll.py", "now")

    # git

    def clean(self):
        return self.ok("git", "status", "--porcelain") == ""

    def current_branch(self):
        return self.ok("git", "branch", "--show-current")

    def leave(self):
        """Push the checked-out branch before a switch; pause if that fails."""
        branch = self.current_branch()
        code, out, _ = self.run("leave-branch.py", branch)
        if out == "dirty":
            self.send(f"{self.prefix()}{DIRTY}", "cleanup", "status")
            self.pause()
        if code != 0:
            error = out.removeprefix("push failed: ")
            self.send(
                f"{self.prefix()}Push von {branch} fehlgeschlagen: {error}, nach Behebung weiter"
            )
            self.pause()

    def switch(self, branch, create_from=None):
        self.leave()
        if create_from:
            self.ok("git", "switch", "-c", branch, create_from)
        else:
            self.ok("git", "switch", branch)

    def to_default(self):
        default = self.default_branch()
        self.switch(default)
        self.ok("git", "pull", "--ff-only")
        return default

    def prefix(self):
        return f"#{self.s['issue']} " if self.s["issue"] else ""

    # events

    def handle(self, event, args, text):
        try:
            if event == "start":
                self.on_start(args[0] if args else "")
            elif event == "telegram":
                self.stop_poller()
                self.on_telegram(args[0], text.strip())
            elif event == "started":
                self.on_started(args[0])
            elif event == "done":
                self.on_done(args[0], text)
            else:
                raise ValueError(event)
        except Wait:
            pass
        except RuntimeError as error:
            # A failed command: keep the state as it was, so `weiter` repeats the event.
            self.s = self.before
            self.actions = [a for a in self.actions if "stop" in a]
            self.s["paused"] = True
            if self.s["waiting_for"] is None:
                self.s["waiting_for"] = "resume"
            self.send(f"{self.prefix()}Fehler: {error}, nach Behebung weiter")
        self.start_poller()

    def on_start(self, label):
        self.stop_poller()
        self.run("release-changed.sh", "record")
        self.s["label"] = label or "ready"
        self.s["pending"] = None
        waiting = self.s["waiting_for"]
        # A fork or task ends with the session: a CI wait starts again, a step reruns.
        if waiting in RUNNING:
            self.s["task_id"] = None
        if waiting == "ci":
            self.start_ci()
        if waiting == "merge_ci":
            self.start_merge_ci()
        if waiting in ("restart", "step"):
            self.s["waiting_for"] = None
            if self.s["park"]:
                self.park(self.s["park"])
            if self.s["question"]:
                self.search_answer(count=False)
        if self.s["paused"] or self.s["waiting_for"] == "new_issue":
            self.wait()
        self.loop()

    def on_started(self, task_id):
        pending, self.s["pending"] = self.s["pending"], None
        if pending == "poller":
            self.s["poller"] = task_id
        elif pending:
            self.s["task_id"] = task_id
        self.wait()

    def on_done(self, task_id, text):
        if task_id == self.s["poller"]:
            self.s["poller"] = None
            self.on_poll_exit()
        elif task_id == self.s["task_id"] and self.s["waiting_for"] in RUNNING:
            self.s["task_id"] = None
            waiting, self.s["waiting_for"] = self.s["waiting_for"], None
            if waiting == "ci":
                self.on_ci()
            elif waiting == "merge_ci":
                self.after_merge_ci()
            else:
                if self.s["step"] == "review-issue" and not self.s["question"]:
                    text = self.task_file("step", ".out") or ""
                self.on_result(parse_result(text))
        # Any other end is a stopped fork or poller.
        self.wait()

    # loop

    def loop(self):
        """Loop steps 2 to 4: check the tree, pick the issue, run its step."""
        if not self.clean():
            self.send(f"{self.prefix()}{DIRTY}", "cleanup", "status")
            self.pause()
        if self.s["issue"] is None:
            self.pick_issue()
        self.run_step()

    def pick_issue(self):
        code, release, error = self.run("release-changed.sh")
        if code != 0:
            self.send(f"Release-Prüfung fehlgeschlagen: {error or release}")
        elif release:
            self.to_default()
            self.restart(f"Autopilot startet neu auf {release}")
        if self.resume_parked():
            return
        untriaged = self.lines("autopilot-poll.py", "untriaged", self.s["label"])
        if untriaged:
            issue = min(untriaged, key=lambda i: i["number"])
            self.to_default()
            self.s.update(issue=issue["number"], step="setprio", branch=None, pr=None)
            if "followup" in issue["labels"]:
                body = self.ok(
                    "gh",
                    "issue",
                    "view",
                    str(issue["number"]),
                    "--json",
                    "body",
                    "--jq",
                    ".body",
                )
                sentence = re.split(r"(?<=[.!?])\s", body.strip(), maxsplit=1)[0]
                self.send(
                    f"#{issue['number']} Neues Folge-Issue: {issue['title']}. {sentence}"
                )
            return
        found = self.lines("autopilot-poll.py", "next", self.s["label"])
        if not found:
            self.send(f"Keine Issues mit Label {self.s['label']}")
            self.s["waiting_for"] = "new_issue"
            self.wait()
        issue = found[0]
        default = self.to_default()
        branch = f"issue-{issue['number']}-{slug(issue['title'])}"
        self.ok("git", "switch", "-c", branch, default)
        self.s.update(issue=issue["number"], branch=branch, pr=None, step="plan-issue")

    def lines(self, *args):
        return [json.loads(line) for line in self.ok(*args).splitlines() if line]

    def targets(self):
        targets = []
        for entry in self.waiting_entries():
            if entry["waiting_for"] == "patch":
                targets += ["patch", entry["branch"], entry["events_since"]]
            else:
                targets += ["answer", str(entry["issue"]), entry["events_since"]]
        return targets

    def waiting_entries(self):
        return [e for e in self.s["parked"] if e.get("answer") is None]

    def collect_answers(self):
        if not self.waiting_entries():
            return
        for event in self.lines("autopilot-poll.py", "check", *self.targets()):
            for entry in self.waiting_entries():
                if event["type"] == "comment" and event["number"] == entry["issue"]:
                    entry["answer"] = event["body"]
                elif event["type"] == "commit" and event["branch"] == entry["branch"]:
                    entry["answer"] = "Der Maintainer hat den Patch committet."

    def resume_parked(self):
        self.collect_answers()
        answered = [e for e in self.s["parked"] if e.get("answer") is not None]
        if not answered:
            return False
        entry = min(answered, key=lambda e: e["issue"])
        pr = entry["pr"]
        if entry["branch"] is None:
            self.to_default()
        else:
            if pr is None:
                pr = self.issue_pr(entry["issue"])["pr"]
            self.switch(entry["branch"])
            if pr is not None or entry["waiting_for"] == "patch":
                self.ok("git", "pull", "--ff-only", "origin", entry["branch"])
        self.s["parked"].remove(entry)
        for field in PARKED_FIELDS:
            if field != "question":
                self.s[field] = entry.get(field, ISSUE_FIELDS[field])
        self.s.update(pr=pr, waiting_for=None, question=None)
        self.log("resume")
        self.run_step(entry["answer"])
        return True

    def issue_pr(self, issue):
        return json.loads(self.ok("issue-pr.py", str(issue)))

    def run_step(self, answer=""):
        """Loop step 4: start the step of the current issue."""
        step = self.s["step"]
        if step != "setprio":
            self.set_label(self.s["issue"], STEP_LABELS[step])
        counts = self.s["attempts_per_step"]
        counts[step] = counts.get(step, 0) + 1
        self.log("start")
        if step == "review-issue":
            self.s["head"] = self.head_sha()
            self.background(f"step gate review {self.s['pr']} {self.s['head']}")
        else:
            self.start_skill(step, answer, self.s["failure"] or "")
        self.s["waiting_for"] = "step"
        self.s["pending"] = "step"
        self.wait()

    def background(self, task):
        self.act(background=f"autopilot-task.py {task}", timeout=BACKGROUND_MS)

    def start_skill(self, step, first, second):
        quoted = " ".join(
            f'"{value.replace(chr(34), chr(39))}"' for value in (first, second)
        )
        self.act(skill=f"pipeline:{step}", args=f"{self.s['issue']} {quoted}")

    # results of a step

    def on_result(self, result):
        if result and result.get("PIPELINE_FINDING"):
            self.send(f"{self.prefix()}Pipeline-Befund: {result['PIPELINE_FINDING']}")
        if self.s["question"]:
            self.on_search_result(result)
            return
        step = self.s["step"]
        status = result["STATUS"] if result else None
        if status == "done" and step in CLEAN_STEPS and not self.clean():
            status = "blocked"
            result["SUMMARY"] = "Arbeitsbaum nach einem lesenden Schritt nicht sauber"
        hold = self.s["paused"] or self.s["park"]
        if status == "needs_input" and result.get("PATCH"):
            self.patch(result["PATCH"], hold)
        elif status == "needs_input":
            self.question(
                result.get("OPEN_QUESTIONS") or result.get("SUMMARY", ""), hold
            )
        elif status != "done":
            self.failure(result["SUMMARY"] if result else "Kein Ergebnisblock", hold)
        else:
            self.transition(step, result, hold)
        self.after_hold(hold)

    def after_hold(self, hold):
        if not hold:
            return
        if self.s["park"]:
            self.park(self.s["park"])
        self.s["waiting_for"] = "resume"
        self.wait()

    def change_step(self, step):
        self.s.update(step=step, attempts=0, failure=None)

    def transition(self, step, result, hold):
        if step == "setprio":
            if self.s["park"]:
                return
            self.setprio_done()
        elif step == "plan-issue":
            self.change_step("issue")
        elif step == "issue":
            pr = self.ok(
                "gh",
                "pr",
                "list",
                "--head",
                self.s["branch"],
                "--json",
                "number",
                "--jq",
                ".[0].number",
            )
            self.s["pr"] = int(pr) if pr else None
            self.change_step("review-issue")
        elif step == "fix-review":
            self.change_step("review-issue")
        elif step == "review-issue":
            verdict = result.get("VERDICT", "")
            if verdict == "approve":
                self.s.update(attempts=0, failure=None)
                if not hold:
                    self.step_seven()
                return
            if verdict != "changes requested":
                self.failure(f"Kein Verdict: {result.get('SUMMARY', '')}", hold)
                return
            self.changes_requested(result.get("SUMMARY", ""), "", hold)
            return
        if not hold:
            self.run_step()

    def changes_requested(self, summary, answer, hold):
        self.s["review_rounds"] += 1
        self.change_step("fix-review")
        rounds = self.s["review_rounds"]
        if rounds >= REVIEW_LIMIT_ROUNDS:
            self.send(
                f"#{self.s['issue']} Review-Limit erreicht, offene Befunde: {summary}"
            )
            self.s["park"] = "Review-Limit"
            if not hold:
                self.park("Review-Limit")
            return
        if rounds == REVIEW_INFO_ROUNDS:
            self.send(
                f"#{self.s['issue']} 3 Review-Runden gelaufen, noch nicht approved"
            )
        if not hold:
            self.run_step(answer)

    def failure(self, summary, hold=False):
        self.s["attempts"] += 1
        self.s["failure"] = summary
        self.log(f"failure {summary}")
        if self.s["attempts"] < MAX_ATTEMPTS:
            if not hold:
                self.run_step()
            return
        self.send(f"#{self.s['issue']} {self.s['step']} fehlgeschlagen: {summary}")
        self.s["park"] = "Fehlversuche"
        if not hold:
            self.park("Fehlversuche")

    def patch(self, url, hold=False):
        self.send(
            f"#{self.s['issue']} Blockierte Änderung als Patch: {url}. "
            f"Bitte auf {self.s['branch']} committen und pushen.",
            "status",
        )
        self.s["park"] = "Patch"
        if not hold:
            self.park("Patch")

    def question(self, questions, hold=False):
        self.s["questions"] += 1
        self.s["question"] = questions
        self.set_label(self.s["issue"], "question")
        n = self.s["issue"]
        items = numbered(questions)
        if len(items) > 1:
            buttons = [f"#{n} Empfehlungen"]
        else:
            buttons = [f"#{n} {letter}" for letter in options(questions)]
        self.send(f"#{n} Rückfrage:\n{questions}", *buttons)
        if hold:
            self.s["park"] = (
                self.s["park"] if self.s["park"] != "manuell" else "Rückfrage"
            )
            self.s["park"] = self.s["park"] or "Rückfrage"
            self.park(self.s["park"])
        self.search_answer()

    def search_answer(self, count=True):
        if count:
            self.s["events_since"] = self.github_now()
        self.act(
            skill="pipeline:find-answer",
            args=f'{self.s["issue"]} "{self.s["question"].replace(chr(34), chr(39))}" ""',
        )
        self.s["waiting_for"] = "step"
        self.s["pending"] = "step"
        self.wait()

    def on_search_result(self, result):
        n = self.s["issue"]
        comments = [
            e["body"]
            for e in self.lines(
                "autopilot-poll.py", "check", "answer", str(n), self.s["events_since"]
            )
            if e["type"] == "comment"
        ]
        if comments:
            answer = "\n\n".join(comments)
            self.s["question"] = None
            if self.s["park"] or self.s["paused"]:
                self.park(self.reason("Rückfrage"), answer)
            self.run_step(answer)
        status = result["STATUS"] if result else None
        if status == "done":
            summary = result.get("SUMMARY", "")
            self.comment(n, f"Antwort gefunden: {summary}")
            self.send(f"#{n} Antwort gefunden: {summary}")
            self.s["question"] = None
            if self.s["park"]:
                self.park(self.s["park"])
            if self.s["paused"]:
                self.park("Rückfrage", summary)
            self.run_step(summary)
        self.park(self.reason("Rückfrage"))

    def reason(self, default):
        return (
            self.s["park"]
            if self.s["park"] and self.s["park"] != "manuell"
            else (self.s["park"] or default)
        )

    # step 7 and merge

    def step_seven(self):
        code, out, err = self.run("merge-default-branch.py")
        if out == "merged":
            self.ok("git", "push", "origin", self.s["branch"])
            self.log("merged default branch")
            self.run_step()
        if out == "conflict":
            self.conflict()
        if code != 0:
            self.failure(err or out)
            return
        self.start_ci()

    def start_ci(self):
        self.s["head"] = self.head_sha()
        branch, pr, sha = self.s["branch"], self.s["pr"], self.s["head"]
        self.background(
            f"step sh -c 'watch-ci.py {branch} {sha} && agent-review.py sync {pr} {sha}'"
        )
        self.s["waiting_for"] = "ci"
        self.s["pending"] = "step"
        self.wait()

    def on_ci(self):
        hold = self.s["paused"] or self.s["park"]
        code = self.task_file("step", ".exit")
        out = self.task_file("step", ".out") or ""
        last = out.splitlines()[-1] if out else ""
        if code != "0" or last != "green":
            self.failure(out or "CI ohne Ergebnis", hold)
            self.after_hold(hold)
            return
        code, threads, err = self.run("open-review-threads.py", str(self.s["pr"]))
        if code != 0:
            self.failure(err or threads, hold)
        elif urls := [t["url"] for t in json.loads(threads)]:
            answer = "Offene Review-Threads: " + " ".join(urls)
            self.changes_requested("", answer, hold)
        else:
            self.set_label(self.s["issue"], "approved")
            if not hold:
                self.merge()
        self.after_hold(hold)

    def merge(self):
        code, out, err = self.run("gate", "merge", str(self.s["pr"]), self.s["head"])
        if code != 0:
            self.failure(err or out)
            return
        default = self.default_branch()
        self.ok("git", "switch", default)
        self.ok("git", "pull", "--ff-only")
        sha = self.ok(
            "gh",
            "pr",
            "view",
            str(self.s["pr"]),
            "--json",
            "mergeCommit",
            "--jq",
            ".mergeCommit.oid",
        )
        self.s["merge"] = {"default": default, "sha": sha}
        self.log("merged")
        self.start_merge_ci()

    def start_merge_ci(self):
        merge = self.s["merge"]
        self.background(f"step watch-ci.py {merge['default']} {merge['sha']}")
        self.s["waiting_for"] = "merge_ci"
        self.s["pending"] = "step"
        self.wait()

    def after_merge_ci(self):
        n, merge = self.s["issue"], self.s["merge"]
        out = self.task_file("step", ".out") or "missing"
        red = self.task_file("step", ".exit") != "0"
        paused = self.s["paused"]
        if red:
            detail = {
                "missing": "kein CI-Lauf gefunden",
                "timeout": "CI nach 45 Minuten nicht fertig",
            }.get(out.splitlines()[-1], out)
            self.send(
                f"#{n} {merge['default']} rot nach Merge: {detail}", "weiter", "status"
            )
        code, _, err = self.run("pipeline-metrics.py", "record")
        if code != 0:
            self.send(f"#{n} Kennzahlen nicht erfasst: {err}")
        state = self.ok(
            "gh", "issue", "view", str(n), "--json", "state", "--jq", ".state"
        )
        if state == "OPEN":
            self.run("gh", "issue", "close", str(n))
        self.set_label(n, None)
        url = self.ok(
            "gh", "pr", "view", str(self.s["pr"]), "--json", "url", "--jq", ".url"
        )
        self.log("done")
        self.reset(keep_paused=False)
        if red or paused:
            self.s.update(paused=True, waiting_for="resume")
        self.send(f"#{n} fertig: {url}")
        if self.s["paused"]:
            self.wait()
        self.loop()

    def conflict(self):
        self.change_step("review-issue")
        self.send(
            f"#{self.s['issue']} Merge-Konflikt mit {self.default_branch()} auf {self.s['branch']}"
        )
        self.park("Merge-Konflikt")

    # parking and resetting

    def reset(self, keep_paused):
        paused = self.s["paused"]
        self.s.update(json.loads(json.dumps(ISSUE_FIELDS)))
        self.s["paused"] = paused if keep_paused else False

    def setprio_done(self):
        self.set_label(self.s["issue"], "ready")
        self.log("ready")
        self.reset(keep_paused=True)
        if self.s["paused"]:
            self.s["waiting_for"] = "resume"
            self.wait()
        self.loop()

    def park(self, reason, answer=None):
        self.s["park"] = reason
        if self.s["branch"]:
            code, out, _ = self.run("leave-branch.py", self.s["branch"])
            if code != 0:
                if out == "dirty":
                    self.send(f"{self.prefix()}{DIRTY}", "cleanup", "status")
                else:
                    self.send(
                        f"{self.prefix()}Push von {self.s['branch']} fehlgeschlagen: "
                        f"{out.removeprefix('push failed: ')}, nach Behebung weiter"
                    )
                self.s.update(paused=True, waiting_for="resume")
                self.wait()
        n = self.s["issue"]
        was_paused = self.s["paused"]
        self.set_label(n, "parked")
        patch = reason == "Patch"
        entry = {field: self.s[field] for field in PARKED_FIELDS}
        entry.update(
            events_since=self.ok("git", "rev-parse", "HEAD")
            if patch
            else self.github_now(),
            waiting_for="patch" if patch else "answer",
            answer=answer,
            reason=reason,
        )
        self.log(f"park {reason}")
        self.s["parked"].append(entry)
        self.reset(keep_paused=True)
        if reason not in ("Rückfrage", "Patch"):
            self.send(f"#{n} geparkt ({reason})", f"#{n} weiter", "status")
        if was_paused:
            self.wait()
        self.loop()

    # restart

    def restart(self, message):
        if (Path(".claude") / "pipeline-release").exists():
            code, out, err = self.run(".claude/skills/pipeline/host/use-release.sh")
            if code != 0:
                self.send(err or out)
                self.s.update(paused=True, waiting_for="resume")
                self.wait()
        self.send(message)
        self.save()
        code, _, _ = self.run("autopilot-restart.sh")
        if code != 0:
            self.send("Kein Dienst, bitte Autopilot neu starten")
            self.s["waiting_for"] = "restart"
        self.wait()

    # poller

    def start_poller(self):
        if (
            self.s["waiting_for"] != "new_issue"
            or self.s["paused"]
            or self.s["poller"]
            or self.s["pending"]
        ):
            return
        targets = " ".join(self.targets())
        self.background(
            f"poller autopilot-poll.py wait new_issue {self.s['label']} {targets}".strip()
        )
        self.s["pending"] = "poller"

    def on_poll_exit(self):
        code = self.task_file("poller", ".exit")
        if code is None:
            # Killed at the limit of a background call: no failure, start it again.
            self.wait()
        if code != "0":
            self.s["poll_failures"] += 1
            if self.s["poll_failures"] >= MAX_POLL_FAILURES:
                error = self.task_file("poller", ".out") or "Poller fehlgeschlagen"
                self.send(f"Poller fehlgeschlagen: {error}")
                self.s.update(poll_failures=0, paused=True, waiting_for="resume")
            self.wait()
        self.s["poll_failures"] = 0
        self.s["waiting_for"] = None
        self.loop()

    # Telegram

    def reply(self, text, *buttons):
        self.send(text, *buttons)
        self.wait()

    def on_telegram(self, chat_id, text):
        self.s["chat_id"] = chat_id
        match = COMMAND.match(text)
        waiting = self.s["waiting_for"]
        running = waiting in RUNNING
        if waiting == "restart" and not (
            match and match["simple"] in ("status", "help", "/verbose")
        ):
            self.reply("Autopilot braucht einen Neustart")
        if match is None:
            self.reply(f"Bitte mit #{self.s['issue'] or '<n>'} antworten")
        if match["answer"]:
            self.answer(int(match["answer"]), match["text"].strip())
        simple = match["simple"]
        if simple == "help":
            self.reply(help_text())
        if simple == "status":
            self.status()
        if simple == "/verbose":
            self.s["verbose"] = not self.s["verbose"]
            self.reply("Verbose an" if self.s["verbose"] else "Verbose aus")
        if match["label"]:
            self.s["label"] = match["label"]
            self.send(f"Label {match['label']}")
            if waiting == "new_issue" and not self.s["paused"]:
                self.s["waiting_for"] = None
                self.loop()
            self.wait()
        if simple == "pause":
            self.s["paused"] = True
            if waiting is None:
                self.s["waiting_for"] = "resume"
            self.reply("Pause nach dem laufenden Schritt" if running else PAUSED)
        if match["park"]:
            self.park_command(match["park"], int(match["park_n"]))
        if running:
            if simple == "weiter":
                self.s["paused"] = False
                self.reply("Weiter nach dem laufenden Schritt")
            self.reply(f"#{self.s['issue']} Ein Schritt läuft", *self.step_buttons())
        if simple == "weiter":
            self.weiter()
        if simple == "update":
            self.update()
        if simple == "cleanup":
            self.cleanup()
        if match["task"]:
            self.task(match["task"], match["task_n"])
        self.reply(PAUSED)

    def step_buttons(self):
        n = self.s["issue"]
        return (f"park #{n}", f"stop #{n}") if n else ()

    def status(self):
        s = self.s
        parts = []
        if s["issue"]:
            parts.append(
                f"#{s['issue']} {s['step']}, Versuche {s['attempts']}, Review-Runden {s['review_rounds']}"
            )
        else:
            parts.append("kein aktuelles Issue")
        parts.append(f"Label {s['label']}")
        if s["paused"]:
            parts.append("pausiert")
        if s["waiting_for"] in RUNNING:
            parts.append("ein Schritt läuft")
        for entry in s["parked"]:
            answer = "Antwort da" if entry.get("answer") is not None else "wartet"
            parts.append(f"geparkt #{entry['issue']} ({entry['reason']}, {answer})")
        buttons = self.step_buttons() if s["waiting_for"] in RUNNING else ()
        self.reply("\n".join(parts), *buttons)

    def answer(self, n, text):
        entry = next((e for e in self.s["parked"] if e["issue"] == n), None)
        current = n == self.s["issue"] and self.s["question"]
        if entry is None and not current:
            self.reply(f"#{n} wartet nicht auf eine Antwort")
        question = entry["question"] if entry else self.s["question"]
        text = expand(text, question)
        self.comment(n, f"Antwort des Maintainers (Telegram): {text}")
        if entry is not None:
            entry["answer"] = text
            if (
                self.s["issue"] is None
                and not self.s["paused"]
                and self.s["waiting_for"]
                in (
                    None,
                    "new_issue",
                )
            ):
                self.s["waiting_for"] = None
                self.loop()
            self.wait()
        if self.s["task_id"]:
            self.act(stop=self.s["task_id"])
        self.s.update(question=None, task_id=None, waiting_for=None)
        if self.s["park"] or self.s["paused"]:
            self.park(self.reason("Rückfrage"), text)
        self.run_step(text)

    def park_command(self, command, n):
        if any(e["issue"] == n for e in self.s["parked"]):
            self.reply(f"#{n} ist schon geparkt")
        if n != self.s["issue"]:
            self.reply(f"#{n} ist nicht das aktuelle Issue")
        if self.s["waiting_for"] == "merge_ci":
            self.reply(f"#{n} ist gemergt, Merge wird abgeschlossen")
        if self.s["waiting_for"] not in RUNNING:
            self.park("manuell")
        if command == "park":
            self.s["park"] = "manuell"
            self.reply(f"#{n} wird nach dem Schritt geparkt")
        if self.s["task_id"]:
            self.act(stop=self.s["task_id"])
        self.s.update(task_id=None, waiting_for=None)
        self.park("abgebrochen")

    def weiter(self):
        if not self.s["paused"]:
            self.reply("Läuft bereits")
        self.s["paused"] = False
        if self.s["park"]:
            self.park(self.s["park"])
        if self.s["pr"]:
            self.ok("git", "pull", "--ff-only", "origin", self.s["branch"])
        if self.s["waiting_for"] in ("resume", None):
            self.s["waiting_for"] = None
            self.loop()
        self.wait()

    def cleanup(self):
        if not self.s["paused"]:
            self.reply("cleanup nur in der Pause")
        match = re.match(r"issue-(\d+)-", self.current_branch())
        if match is None:
            self.reply("Kein Issue-Branch, bitte von Hand aufräumen")
        n = match.group(1)
        code, out, _ = self.run("cleanup-tree.py", n)
        if code != 0:
            self.reply(f"#{n} Nichts zu sichern")
        self.reply(f"#{n} Änderungen auf {out} gesichert, nicht gepusht")

    def update(self):
        if self.s["issue"] is not None or self.s["waiting_for"] not in (
            "new_issue",
            "resume",
        ):
            self.reply("update nur ohne aktuelles Issue")
        if not self.clean():
            self.reply(DIRTY, "cleanup", "status")
        code, release, error = self.run("release-changed.sh")
        if code == 0 and release:
            self.to_default()
            self.restart(f"Autopilot startet neu auf {release}")
        code, out, error = self.run(".claude/skills/pipeline/host/update-pipeline.sh")
        if code != 0:
            self.reply(error or out)
        self.reply(out.splitlines()[-1] if out else "")

    def task(self, task, n):
        if (
            not (self.s["paused"] and self.s["waiting_for"] in ("resume", "new_issue"))
            or task not in TASKS
            or n is None
        ):
            self.reply(PAUSED)
        n = int(n)
        if not self.clean():
            self.reply(f"#{n} {DIRTY}", "cleanup", "status")
        entry = next((e for e in self.s["parked"] if e["issue"] == n), None)
        current = n == self.s["issue"]
        known = entry if entry is not None else (self.s if current else None)
        lookup = None
        if known is None or known.get("pr") is None:
            lookup = self.issue_pr(n)
            if lookup["state"] == "CLOSED":
                self.reply(f"#{n} ist geschlossen")
            if lookup["pr"] is None and task in ("review-issue", "fix-review"):
                self.reply(f"#{n} kein PR, /{task} nicht gestartet")
        try:
            branch = self.prepare_task(n, entry, current, known, lookup)
        except RuntimeError as error:
            self.reply(f"#{n} /{task} nicht gestartet: {error}")
        if self.s["issue"] is not None and not current:
            self.s["paused"] = False
            self.park_without_loop("manuell")
        if entry is not None:
            self.s["parked"].remove(entry)
            for field in PARKED_FIELDS:
                self.s[field] = entry.get(field, ISSUE_FIELDS[field])
            self.s["question"] = None
            if lookup and lookup["pr"]:
                self.s["pr"] = lookup["pr"]
        elif current:
            self.s["question"] = None
            if lookup and lookup["pr"]:
                self.s["pr"] = lookup["pr"]
        else:
            self.reset(keep_paused=True)
            self.s["pr"] = lookup["pr"]
            self.s["review_rounds"] = lookup["review_rounds"]
        self.s.update(issue=n, branch=branch, step=task, attempts=0, failure=None)
        self.s.update(paused=False, waiting_for=None)
        self.log(f"{task} manual start")
        self.loop()

    def prepare_task(self, n, entry, current, known, lookup):
        """Check out the branch of issue n; returns it."""
        pr = (lookup or {}).get("pr") or (known or {}).get("pr")
        branch = (known or {}).get("branch")
        if entry is not None and branch:
            self.switch(branch)
            if pr or entry["waiting_for"] == "patch":
                self.ok("git", "pull", "--ff-only", "origin", branch)
            return branch
        if current and branch:
            if pr:
                self.ok("git", "pull", "--ff-only", "origin", branch)
            return branch
        if lookup and lookup["pr"]:
            branch = lookup["branch"]
            self.ok("git", "fetch", "origin", branch)
            self.switch(branch)
            self.ok("git", "pull", "--ff-only", "origin", branch)
            return branch
        title = self.ok(
            "gh", "issue", "view", str(n), "--json", "title", "--jq", ".title"
        )
        default = self.to_default()
        branch = f"issue-{n}-{slug(title)}"
        code, _, _ = self.run("git", "switch", branch)
        if code != 0:
            self.ok("git", "switch", "-c", branch, default)
        return branch

    def park_without_loop(self, reason):
        try:
            self.park(reason)
        except Wait:
            pass

    # state

    def save(self):
        PIPELINE.mkdir(parents=True, exist_ok=True)
        temp = PIPELINE / "state.json.tmp"
        temp.write_text(json.dumps(self.s, indent=2, ensure_ascii=False) + "\n")
        os.replace(temp, PIPELINE / "state.json")


def load():
    path = PIPELINE / "state.json"
    return json.loads(path.read_text()) if path.exists() else {}


def main(argv):
    match argv:
        case ["event", ("start" | "telegram" | "started" | "done") as event, *args] if (
            event == "start" and len(args) <= 1
        ) or len(args) == 1:
            text = "" if event in ("start", "started") else sys.stdin.read()
            autopilot = Autopilot(load())
            autopilot.handle(event, args, text)
            autopilot.save()
            for action in autopilot.actions:
                print(json.dumps(action, ensure_ascii=False))
        case _:
            sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
