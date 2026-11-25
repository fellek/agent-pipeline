import json

import pytest
from conftest import ROOT, load_script

ISSUE = {"number": 7, "title": "Fix the thing", "labels": []}
DEFAULT_RESULTS = {
    ("git", "status", "--porcelain"): "",
    ("git", "branch", "--show-current"): "main",
    ("git", "rev-parse", "HEAD"): "c" * 40,
    ("default-branch.py",): "main",
    ("release-changed.sh",): "",
    ("autopilot-poll.py", "now"): "2026-01-01T00:00:00Z",
    ("autopilot-poll.py", "untriaged"): "",
    ("autopilot-poll.py", "next"): json.dumps(ISSUE),
    ("autopilot-poll.py", "check"): "",
    ("leave-branch.py",): "clean",
    ("merge-default-branch.py",): "current",
    ("open-review-threads.py",): "[]",
    ("gh", "pr", "view", "5", "--json", "headRefOid"): "a" * 40,
    ("gh", "pr", "view", "5", "--json", "mergeCommit"): "m" * 40,
    ("gh", "pr", "view", "5", "--json", "url"): "https://pr/5",
    ("gh", "pr", "list"): "5",
    ("gh", "issue", "view", "7", "--json", "state"): "OPEN",
    ("issue-pr.py",): json.dumps(
        {"state": "OPEN", "pr": None, "branch": None, "review_rounds": 0}
    ),
}


class Harness:
    def __init__(self, module, folder):
        self.module = module
        self.folder = folder
        self.state = {}
        self.results = dict(DEFAULT_RESULTS)
        self.calls = []
        self.sent = []

    def result(self, *prefix, out="", code=0, err=""):
        self.results[prefix] = (code, out, err)

    def task(self, name, out, code=0):
        tasks = self.folder / "tasks"
        tasks.mkdir(parents=True, exist_ok=True)
        (tasks / f"{name}.out").write_text(out)
        if code is not None:
            (tasks / f"{name}.exit").write_text(f"{code}\n")

    def run(self, *args, input=None):
        self.calls.append(args)
        if args[0] == "telegram-send.py":
            self.sent.append((input, args[1:]))
            return 0, "", ""
        best = max(
            (key for key in self.results if args[: len(key)] == key),
            key=len,
            default=None,
        )
        if best is None:
            return 0, "", ""
        found = self.results[best]
        return found if isinstance(found, tuple) else (0, found, "")

    def event(self, name, *args, text=""):
        self.calls, self.sent = [], []
        pilot = self.module.Autopilot(self.state)
        pilot.run = self.run
        pilot.save = lambda: None
        pilot.handle(name, list(args), text)
        self.state = pilot.s
        return pilot.actions

    def ran(self, *prefix):
        return any(call[: len(prefix)] == prefix for call in self.calls)

    def texts(self):
        return [text for text, _ in self.sent]

    def labels(self):
        return [
            call[call.index("--add-label") + 1] if "--add-label" in call else None
            for call in self.calls
            if call[:3] == ("gh", "issue", "edit")
        ]


@pytest.fixture
def pilot(tmp_path, monkeypatch):
    module = load_script("autopilot-state.py")
    monkeypatch.setattr(module, "PIPELINE", tmp_path)
    return Harness(module, tmp_path)


def result(status="done", **fields):
    lines = [f"STATUS: {status}", f"SUMMARY: {fields.pop('summary', 's')}"]
    lines += [f"{key.upper()}: {value}" for key, value in fields.items()]
    return "\n".join(lines)


def at_step(pilot, step, **fields):
    pilot.state = {
        "issue": 7,
        "branch": "issue-7-fix-the-thing",
        "pr": 5,
        "step": step,
        "waiting_for": "step",
        "task_id": "t1",
        **fields,
    }


def finish(pilot, text="", **task):
    if task:
        pilot.task("step", **task)
    return pilot.event("done", "t1", text=text)


# Start and selection


def test_start_picks_the_next_issue_and_plans_it(pilot):
    actions = pilot.event("start", "")

    assert pilot.ran("release-changed.sh", "record")
    assert pilot.ran("git", "switch", "-c", "issue-7-fix-the-thing", "main")
    assert pilot.state["step"] == "plan-issue"
    assert pilot.state["waiting_for"] == "step"
    assert pilot.state["attempts_per_step"] == {"plan-issue": 1}
    assert pilot.labels() == ["in-progress"]
    assert actions == [{"skill": "pipeline:plan-issue", "args": '7 "" ""'}]


def test_started_stores_the_task_id(pilot):
    pilot.event("start", "")
    assert pilot.event("started", "t1") == []
    assert pilot.state["task_id"] == "t1"


def test_start_sets_the_label(pilot):
    pilot.event("start", "next")
    assert pilot.state["label"] == "next"
    assert pilot.ran("autopilot-poll.py", "next", "next")


def test_untriaged_issue_goes_to_setprio_first(pilot):
    pilot.result(
        "autopilot-poll.py",
        "untriaged",
        out=json.dumps({"number": 3, "title": "t", "labels": []}),
    )
    actions = pilot.event("start", "")

    assert pilot.state["step"] == "setprio"
    assert pilot.state["branch"] is None
    assert pilot.labels() == []
    assert actions == [{"skill": "pipeline:setprio", "args": '3 "" ""'}]


def test_new_followup_issue_is_announced(pilot):
    pilot.result(
        "autopilot-poll.py",
        "untriaged",
        out=json.dumps({"number": 3, "title": "T", "labels": ["followup"]}),
    )
    pilot.result("gh", "issue", "view", "3", out="First sentence. Second.")
    pilot.event("start", "")
    assert pilot.texts()[0] == "#3 Neues Folge-Issue: T. First sentence."


def test_no_issue_waits_with_the_poller(pilot):
    pilot.result("autopilot-poll.py", "next", out="")
    actions = pilot.event("start", "")

    assert pilot.texts() == ["Keine Issues mit Label ready"]
    assert pilot.state["waiting_for"] == "new_issue"
    assert actions == [
        {
            "background": "autopilot-task.py poller autopilot-poll.py wait new_issue ready",
            "timeout": pilot.module.BACKGROUND_MS,
        }
    ]
    pilot.event("started", "p1")
    assert pilot.state["poller"] == "p1"


def test_poller_exit_looks_for_issues_again(pilot):
    pilot.state = {"waiting_for": "new_issue", "poller": "p1"}
    pilot.task("poller", "", code=0)
    actions = pilot.event("done", "p1")
    assert pilot.state["step"] == "plan-issue"
    assert actions[0]["skill"] == "pipeline:plan-issue"


def test_poller_failures_pause_after_three(pilot):
    pilot.state = {"waiting_for": "new_issue", "poller": "p1"}
    pilot.task("poller", "boom", code=1)
    for _ in range(2):
        actions = pilot.event("done", "p1")
        assert actions[0]["background"].startswith("autopilot-task.py poller")
        pilot.event("started", "p1")
    assert pilot.event("done", "p1") == []
    assert pilot.texts() == ["Poller fehlgeschlagen: boom"]
    assert pilot.state["paused"] is True
    assert pilot.state["waiting_for"] == "resume"


def test_poller_killed_at_its_time_limit_starts_again(pilot):
    pilot.state = {"waiting_for": "new_issue", "poller": "p1"}
    pilot.task("poller", "", code=None)
    actions = pilot.event("done", "p1")
    assert actions[0]["background"].startswith("autopilot-task.py poller")
    assert pilot.state["poll_failures"] == 0


def test_stale_done_is_ignored(pilot):
    at_step(pilot, "issue")
    assert pilot.event("done", "old", text=result()) == []
    assert pilot.state["step"] == "issue"


def test_dirty_tree_pauses(pilot):
    pilot.result("git", "status", "--porcelain", out=" M a.py")
    assert pilot.event("start", "") == []
    assert pilot.sent[0][1] == ("cleanup", "status")
    assert pilot.state["paused"] is True


def test_new_release_restarts(pilot):
    pilot.result("release-changed.sh", out="v2")
    pilot.event("start", "")
    assert pilot.ran("autopilot-restart.sh")
    assert "Autopilot startet neu auf v2" in pilot.texts()


def test_restart_without_service_waits_for_a_restart(pilot):
    pilot.result("release-changed.sh", out="v2")
    pilot.result("autopilot-restart.sh", code=1)
    pilot.event("start", "")
    assert pilot.state["waiting_for"] == "restart"
    assert pilot.texts()[-1] == "Kein Dienst, bitte Autopilot neu starten"


# Transitions of loop step 6


@pytest.mark.parametrize(
    ("step", "next_step", "label"),
    [
        ("plan-issue", "issue", "in-progress"),
    ],
)
def test_done_starts_the_next_step(pilot, step, next_step, label):
    at_step(pilot, step, attempts=2, failure="x")
    actions = finish(pilot, result())
    assert pilot.state["step"] == next_step
    assert pilot.state["attempts"] == 0
    assert pilot.state["failure"] is None
    assert pilot.labels() == [label]
    assert actions


def test_issue_done_stores_the_pull_request(pilot):
    at_step(pilot, "issue", pr=None)
    pilot.result("gh", "pr", "list", out="9")
    pilot.result("gh", "pr", "view", "9", "--json", "headRefOid", out="b" * 40)
    actions = finish(pilot, result())
    assert pilot.state["pr"] == 9
    assert actions[0]["background"].endswith(
        f"watch-ci.py issue-7-fix-the-thing {'b' * 40}"
    )


@pytest.mark.parametrize("step", ["issue", "fix-review"])
def test_ci_runs_before_the_review(pilot, step):
    at_step(pilot, step)
    actions = finish(pilot, result())
    assert pilot.state["step"] == "review-issue"
    assert pilot.labels() == ["in-review"]
    assert pilot.state["waiting_for"] == "review_ci"
    assert actions == [
        {
            "background": f"autopilot-task.py step watch-ci.py issue-7-fix-the-thing {'a' * 40}",
            "timeout": pilot.module.BACKGROUND_MS,
        }
    ]


def at_review_ci(pilot, step="review-issue", **fields):
    at_step(pilot, step, waiting_for="review_ci", head="a" * 40, **fields)


def test_review_runs_through_the_gate_after_green_ci(pilot):
    at_review_ci(pilot)
    actions = finish(pilot, out="green", code=0)
    assert pilot.state["waiting_for"] == "step"
    assert actions == [
        {
            "background": f"autopilot-task.py step gate review 5 {'a' * 40}",
            "timeout": pilot.module.BACKGROUND_MS,
        }
    ]


def test_review_result_comes_from_the_task_output(pilot):
    at_step(pilot, "review-issue")
    actions = finish(pilot, out=result(verdict="changes requested"))
    assert pilot.state["step"] == "fix-review"
    assert pilot.state["review_rounds"] == 1
    assert actions[0]["skill"] == "pipeline:fix-review"


def test_setprio_done_sets_ready_and_resets(pilot):
    at_step(pilot, "setprio", branch=None, pr=None, issue=3)
    pilot.result("autopilot-poll.py", "next", out="")
    finish(pilot, result())
    assert pilot.labels()[0] == "ready"
    assert pilot.state["issue"] is None
    assert pilot.state["waiting_for"] == "new_issue"


def test_dirty_tree_after_a_reading_step_is_a_failure(pilot):
    at_step(pilot, "plan-issue")
    pilot.result("git", "status", "--porcelain", out=" M a.py")
    finish(pilot, result())
    assert pilot.state["attempts"] == 1
    assert "nicht sauber" in pilot.state["failure"]


@pytest.mark.parametrize(
    ("rounds", "message", "parked"),
    [(1, None, False), (2, "3 Review-Runden", False), (4, "Review-Limit", True)],
)
def test_review_rounds(pilot, rounds, message, parked):
    at_step(pilot, "review-issue", review_rounds=rounds)
    finish(pilot, out=result(verdict="changes requested", summary="open"))
    assert pilot.state["review_rounds"] == (0 if parked else rounds + 1)
    if message:
        assert any(message in text for text in pilot.texts())
    entry = pilot.state["parked"][0] if parked else None
    assert (entry or {}).get("reason") == ("Review-Limit" if parked else None)
    if parked:
        assert entry["step"] == "fix-review"
        assert entry["review_rounds"] == 5


def test_failure_reruns_twice_then_parks(pilot):
    at_step(pilot, "issue")
    for attempt in (1, 2):
        actions = finish(pilot, result("blocked", summary="broken"))
        assert pilot.state["attempts"] == attempt
        assert actions[0]["args"] == '7 "" "broken"'
        pilot.event("started", "t1")
    pilot.result("autopilot-poll.py", "next", out="")
    finish(pilot, result("blocked", summary="broken"))
    assert pilot.texts()[0] == "#7 issue fehlgeschlagen: broken"
    assert pilot.state["parked"][0]["reason"] == "Fehlversuche"
    assert "#7 geparkt (Fehlversuche)" in pilot.texts()


def test_missing_result_block_is_a_failure(pilot):
    at_step(pilot, "issue")
    finish(pilot, "no block")
    assert pilot.state["failure"] == "Kein Ergebnisblock"


def test_pipeline_finding_is_sent(pilot):
    at_step(pilot, "plan-issue")
    finish(pilot, result(pipeline_finding="https://c/1"))
    assert pilot.texts()[0] == "#7 Pipeline-Befund: https://c/1"


# Question and find-answer


QUESTION = "1. Which? a) x b) y Recommendation: a"


def test_question_searches_for_an_answer(pilot):
    at_step(pilot, "plan-issue")
    actions = finish(pilot, result("needs_input", open_questions=QUESTION))
    assert pilot.state["question"] == QUESTION
    assert pilot.state["questions"] == 1
    assert pilot.state["events_since"] == "2026-01-01T00:00:00Z"
    assert pilot.labels() == ["question"]
    assert pilot.sent[0][1] == ("#7 a", "#7 b")
    assert actions == [{"skill": "pipeline:find-answer", "args": f'7 "{QUESTION}" ""'}]


def test_found_answer_reruns_the_step(pilot):
    at_step(pilot, "plan-issue", question=QUESTION, events_since="t0")
    actions = finish(pilot, result(summary="use x"))
    assert pilot.ran("gh", "issue", "comment", "7")
    assert "#7 Antwort gefunden: use x" in pilot.texts()
    assert pilot.state["question"] is None
    assert actions[0] == {"skill": "pipeline:plan-issue", "args": '7 "use x" ""'}


def test_maintainer_comment_beats_the_search(pilot):
    at_step(pilot, "plan-issue", question=QUESTION, events_since="t0")
    pilot.result(
        "autopilot-poll.py",
        "check",
        out=json.dumps({"type": "comment", "number": 7, "body": "b"}),
    )
    actions = finish(pilot, result(summary="use x"))
    assert actions[0]["args"] == '7 "b" ""'


def test_no_answer_parks_with_rueckfrage(pilot):
    at_step(pilot, "plan-issue", question=QUESTION, events_since="t0")
    pilot.result("autopilot-poll.py", "next", out="")
    finish(pilot, result("needs_input"))
    entry = pilot.state["parked"][0]
    assert entry["reason"] == "Rückfrage"
    assert entry["question"] == QUESTION
    assert entry["answer"] is None
    assert "#7 geparkt" not in " ".join(pilot.texts())


def test_several_questions_get_the_recommendation_button(pilot):
    at_step(pilot, "plan-issue")
    finish(pilot, result("needs_input", open_questions="x"))
    pilot.state["task_id"] = "t1"
    at_step(pilot, "plan-issue")
    finish(pilot, "STATUS: needs_input\nSUMMARY: s\nOPEN_QUESTIONS:\n1. A\n2. B")
    assert pilot.sent[0][1] == ("#7 Empfehlungen",)


def test_patch_parks_waiting_for_a_commit(pilot):
    at_step(pilot, "issue")
    pilot.result("autopilot-poll.py", "next", out="")
    finish(pilot, result("needs_input", patch="https://c/2"))
    entry = pilot.state["parked"][0]
    assert entry["reason"] == "Patch"
    assert entry["waiting_for"] == "patch"
    assert entry["events_since"] == "c" * 40
    assert pilot.sent[0] == (
        (
            "#7 Blockierte Änderung als Patch: https://c/2. "
            "Bitte auf issue-7-fix-the-thing committen und pushen."
        ),
        ("status",),
    )


# Parked issues


def parked(**fields):
    return {
        "issue": 4,
        "branch": "issue-4-x",
        "pr": None,
        "step": "plan-issue",
        "review_rounds": 0,
        "attempts_per_step": {"plan-issue": 1},
        "questions": 1,
        "events_since": "t0",
        "question": QUESTION,
        "waiting_for": "answer",
        "answer": None,
        "reason": "Rückfrage",
        **fields,
    }


def test_parked_issue_with_an_answer_resumes_first(pilot):
    pilot.state = {"parked": [parked()]}
    pilot.result(
        "autopilot-poll.py",
        "check",
        out=json.dumps({"type": "comment", "number": 4, "body": "take a"}),
    )
    actions = pilot.event("start", "")
    assert pilot.ran("autopilot-poll.py", "check", "answer", "4", "t0")
    assert pilot.ran("git", "switch", "issue-4-x")
    assert pilot.state["parked"] == []
    assert pilot.state["issue"] == 4
    assert pilot.state["question"] is None
    assert pilot.state["attempts_per_step"] == {"plan-issue": 2}
    assert actions[0] == {"skill": "pipeline:plan-issue", "args": '4 "take a" ""'}


def test_waiting_parked_entries_are_targets_of_the_poller(pilot):
    pilot.state = {"parked": [parked(), parked(issue=6, waiting_for="patch")]}
    pilot.result("autopilot-poll.py", "next", out="")
    actions = pilot.event("start", "")
    assert actions[0]["background"].endswith(
        "new_issue ready answer 4 t0 patch issue-4-x t0"
    )


def test_park_pushes_and_labels(pilot):
    at_step(pilot, "plan-issue", waiting_for=None, task_id=None)
    pilot.result("autopilot-poll.py", "next", out="")
    pilot.event("telegram", "1", text="park #7")
    assert pilot.ran("leave-branch.py", "issue-7-fix-the-thing")
    assert pilot.labels() == ["parked"]
    assert pilot.state["parked"][0]["reason"] == "manuell"
    assert pilot.sent[0] == ("#7 geparkt (manuell)", ("#7 weiter", "status"))


def test_park_with_a_failed_push_pauses(pilot):
    at_step(pilot, "plan-issue", waiting_for=None, task_id=None)
    pilot.result("leave-branch.py", code=2, out="push failed: denied")
    pilot.event("telegram", "1", text="park #7")
    assert pilot.state["paused"] is True
    assert pilot.state["park"] == "manuell"
    assert pilot.state["parked"] == []
    assert "Push von issue-7-fix-the-thing fehlgeschlagen: denied" in pilot.texts()[0]


# Step 7 and Merge


def test_approve_starts_the_ci_wait(pilot):
    at_step(pilot, "review-issue")
    actions = finish(pilot, out=result(verdict="approve"))
    assert pilot.state["waiting_for"] == "ci"
    sha = "a" * 40
    assert actions == [
        {
            "background": "autopilot-task.py step sh -c 'watch-ci.py "
            f"issue-7-fix-the-thing {sha} && agent-review.py await 5 {sha}'",
            "timeout": pilot.module.BACKGROUND_MS,
        }
    ]


def test_merged_default_branch_pushes_and_reviews_again(pilot):
    at_step(pilot, "review-issue")
    pilot.result("merge-default-branch.py", out="merged")
    pilot.result("gate", "carry", code=1, err="changed files")
    actions = finish(pilot, out=result(verdict="approve"))
    assert pilot.ran("git", "push", "origin", "issue-7-fix-the-thing")
    assert actions[0]["background"].startswith("autopilot-task.py step watch-ci.py")


def test_conflict_parks(pilot):
    at_step(pilot, "review-issue")
    pilot.result("merge-default-branch.py", out="conflict", code=1)
    pilot.result("autopilot-poll.py", "next", out="")
    finish(pilot, out=result(verdict="approve"))
    assert pilot.texts()[0] == "#7 Merge-Konflikt mit main auf issue-7-fix-the-thing"
    assert pilot.state["parked"][0]["reason"] == "Merge-Konflikt"
    assert pilot.state["parked"][0]["step"] == "review-issue"


def at_ci(pilot, **fields):
    at_step(pilot, "review-issue", waiting_for="ci", head="a" * 40, **fields)


def test_green_ci_merges_and_waits_for_the_default_branch(pilot):
    at_ci(pilot)
    actions = finish(pilot, out="green\ngreen", code=0)
    assert pilot.labels() == ["approved"]
    assert pilot.ran("gate", "merge", "5", "a" * 40)
    assert pilot.ran("git", "fetch", "--prune", "origin")
    assert pilot.state["waiting_for"] == "merge_ci"
    assert pilot.state["merge"] == {"default": "main", "sha": "m" * 40}
    assert (
        actions[0]["background"]
        == f"autopilot-task.py step watch-ci.py main {'m' * 40}"
    )


@pytest.mark.parametrize(
    "out", ["red https://run/1", "timeout", "green\nred https://r"]
)
def test_red_ci_is_a_failure(pilot, out):
    at_ci(pilot)
    actions = finish(pilot, out=out, code=1)
    assert pilot.state["failure"] == out
    assert actions[0]["background"].startswith("autopilot-task.py step watch-ci.py")


def test_open_review_threads_go_to_fix_review(pilot):
    at_ci(pilot)
    pilot.result(
        "open-review-threads.py", out=json.dumps([{"url": "u1"}, {"url": "u2"}])
    )
    actions = finish(pilot, out="green", code=0)
    assert pilot.state["step"] == "fix-review"
    assert pilot.state["review_rounds"] == 1
    assert actions[0]["args"] == '7 "Offene Review-Threads: u1 u2" ""'


def test_refused_merge_is_a_failure(pilot):
    at_ci(pilot)
    pilot.result("gate", "merge", code=1, err="no approve")
    finish(pilot, out="green", code=0)
    assert pilot.state["failure"] == "no approve"


def at_merge_ci(pilot, **fields):
    at_step(
        pilot,
        "review-issue",
        waiting_for="merge_ci",
        merge={"default": "main", "sha": "m" * 40},
        **fields,
    )


def test_merge_finishes_the_issue(pilot):
    at_merge_ci(pilot)
    pilot.result("autopilot-poll.py", "next", out="")
    finish(pilot, out="green", code=0)
    assert pilot.ran("pipeline-metrics.py", "record")
    assert pilot.ran("gh", "issue", "close", "7")
    assert pilot.labels() == [None]
    assert "#7 fertig: https://pr/5" in pilot.texts()
    assert pilot.state["issue"] is None
    assert pilot.state["merge"] is None


@pytest.mark.parametrize(
    ("out", "detail"),
    [
        ("red https://run/2", "https://run/2"),
        ("missing", "kein CI-Lauf gefunden"),
        ("timeout", "CI nach 45 Minuten nicht fertig"),
    ],
)
def test_red_default_branch_pauses_after_finishing(pilot, out, detail):
    at_merge_ci(pilot)
    finish(pilot, out=out, code=1)
    assert pilot.sent[0] == (f"#7 main rot nach Merge: {detail}", ("weiter", "status"))
    assert pilot.ran("gh", "issue", "close", "7")
    assert pilot.state["paused"] is True
    assert pilot.state["issue"] is None


def test_pause_during_the_merge_wait_survives(pilot):
    at_merge_ci(pilot, paused=True)
    finish(pilot, out="green", code=0)
    assert pilot.ran("gh", "issue", "close", "7")
    assert pilot.state["paused"] is True
    assert pilot.state["waiting_for"] == "resume"


def test_failed_metrics_are_reported(pilot):
    at_merge_ci(pilot)
    pilot.result("pipeline-metrics.py", code=1, err="no pr")
    pilot.result("autopilot-poll.py", "next", out="")
    finish(pilot, out="green", code=0)
    assert "#7 Kennzahlen nicht erfasst: no pr" in pilot.texts()


# Pause and park while a step runs


def test_result_during_a_pause_is_only_recorded(pilot):
    at_step(pilot, "plan-issue", paused=True)
    assert finish(pilot, result()) == []
    assert pilot.state["step"] == "issue"
    assert pilot.state["waiting_for"] == "resume"


def test_approve_during_a_pause_waits_before_step_seven(pilot):
    at_step(pilot, "review-issue", paused=True)
    assert finish(pilot, out=result(verdict="approve")) == []
    assert not pilot.ran("merge-default-branch.py")
    assert pilot.state["step"] == "review-issue"


def test_pending_park_parks_after_the_step(pilot):
    at_step(pilot, "plan-issue", park="manuell")
    pilot.result("autopilot-poll.py", "next", out="")
    finish(pilot, result())
    entry = pilot.state["parked"][0]
    assert entry["step"] == "issue"
    assert entry["reason"] == "manuell"


def test_question_with_a_pending_park_parks_without_search(pilot):
    at_step(pilot, "plan-issue", park="manuell")
    pilot.result("autopilot-poll.py", "next", out="")
    actions = finish(pilot, result("needs_input", open_questions="Which?"))
    assert not any("skill" in a and a["skill"].endswith("find-answer") for a in actions)
    assert pilot.state["parked"][0]["reason"] == "Rückfrage"


def test_green_ci_during_a_pause_does_not_merge(pilot):
    at_ci(pilot, paused=True)
    finish(pilot, out="green", code=0)
    assert pilot.labels() == ["approved"]
    assert not pilot.ran("gate", "merge")
    assert pilot.state["waiting_for"] == "resume"


# Restart of the session


def test_restart_reruns_a_running_step(pilot):
    at_step(pilot, "issue")
    actions = pilot.event("start", "")
    assert pilot.state["task_id"] is None
    assert actions[0]["skill"] == "pipeline:issue"


def test_restart_starts_the_ci_wait_again(pilot):
    at_ci(pilot)
    actions = pilot.event("start", "")
    assert actions[0]["background"].startswith("autopilot-task.py step sh -c")
    assert pilot.state["waiting_for"] == "ci"


def test_restart_starts_the_merge_wait_again(pilot):
    at_merge_ci(pilot)
    actions = pilot.event("start", "")
    assert actions[0]["background"].endswith(f"watch-ci.py main {'m' * 40}")
    assert not pilot.ran("gate", "merge")


def test_restart_during_a_search_searches_again(pilot):
    at_step(pilot, "plan-issue", question=QUESTION, questions=1, events_since="t0")
    actions = pilot.event("start", "")
    assert actions[0]["skill"] == "pipeline:find-answer"
    assert pilot.state["questions"] == 1
    assert pilot.state["events_since"] == "t0"


def test_restart_with_a_pending_park_parks(pilot):
    at_step(pilot, "issue", park="manuell")
    pilot.result("autopilot-poll.py", "next", out="")
    pilot.event("start", "")
    assert pilot.state["parked"][0]["reason"] == "manuell"


def test_restart_while_paused_waits(pilot):
    pilot.state = {"paused": True, "waiting_for": "resume"}
    assert pilot.event("start", "") == []


def test_restart_waiting_for_new_issues_starts_the_poller(pilot):
    pilot.state = {"waiting_for": "new_issue"}
    actions = pilot.event("start", "")
    assert actions[0]["background"].startswith("autopilot-task.py poller")
    assert not pilot.ran("autopilot-poll.py", "next")


# Telegram


def message(pilot, text):
    return pilot.event("telegram", "42", text=text)


def test_message_stores_the_chat_and_stops_the_poller(pilot, tmp_path):
    pilot.state = {"waiting_for": "new_issue", "poller": "p1"}
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "poller.pid").write_text("999999999\n")
    actions = message(pilot, "status")
    assert pilot.state["chat_id"] == "42"
    assert actions[0]["background"].startswith("autopilot-task.py poller")


def test_unknown_text_asks_for_the_prefix(pilot):
    at_step(pilot, "issue")
    message(pilot, "hello")
    assert pilot.texts() == ["Bitte mit #7 antworten"]


def test_status_reports_issue_label_and_parked(pilot):
    at_step(pilot, "issue", attempts=1, parked=[parked()])
    message(pilot, "status")
    text, buttons = pilot.sent[0]
    assert "#7 issue, Versuche 1" in text
    assert "Auswahl-Label ready" in text
    assert "geparkt #4 (Rückfrage, wartet)" in text
    assert buttons == ("park #7", "stop #7")


def test_help_comes_from_the_docs(pilot):
    message(pilot, "help")
    assert "status" in pilot.texts()[0]


def test_verbose_toggles_and_logs(pilot):
    message(pilot, "/verbose")
    assert pilot.texts() == ["Verbose an"]
    assert pilot.state["verbose"] is True


def test_label_looks_again_while_waiting(pilot):
    pilot.state = {"waiting_for": "new_issue"}
    actions = message(pilot, "label next")
    assert pilot.state["label"] == "next"
    assert pilot.ran("autopilot-poll.py", "next", "next")
    assert actions[0]["skill"] == "pipeline:plan-issue"


def test_pause_while_a_step_runs(pilot):
    at_step(pilot, "issue")
    message(pilot, "pause")
    assert pilot.state["paused"] is True
    assert pilot.state["waiting_for"] == "step"
    assert pilot.texts() == ["Pause nach dem laufenden Schritt"]


def test_pause_without_a_step_keeps_a_pending_wait(pilot):
    pilot.state = {"waiting_for": "new_issue", "events_since": "t0"}
    assert message(pilot, "pause") == []
    assert pilot.state["waiting_for"] == "new_issue"


def test_weiter_continues(pilot):
    pilot.state = {"paused": True, "waiting_for": "resume"}
    actions = message(pilot, "weiter")
    assert pilot.state["paused"] is False
    assert actions[0]["skill"] == "pipeline:plan-issue"


def test_weiter_pulls_the_branch_of_a_pull_request(pilot):
    at_step(pilot, "fix-review", paused=True, waiting_for="resume", task_id=None)
    message(pilot, "weiter")
    assert pilot.ran("git", "pull", "--ff-only", "origin", "issue-7-fix-the-thing")


def test_weiter_while_a_step_runs_only_clears_the_pause(pilot):
    at_step(pilot, "issue", paused=True)
    assert message(pilot, "weiter") == []
    assert pilot.state["paused"] is False
    assert not pilot.ran("git", "pull")


def test_weiter_with_a_pending_park_parks(pilot):
    at_step(pilot, "issue", paused=True, waiting_for="resume", park="manuell")
    message(pilot, "weiter")
    assert pilot.state["parked"][0]["reason"] == "manuell"


def test_other_commands_while_a_step_runs(pilot):
    at_step(pilot, "issue")
    message(pilot, "cleanup")
    assert pilot.sent == [("#7 Ein Schritt läuft", ("park #7", "stop #7"))]


def test_park_while_a_step_runs_parks_afterwards(pilot):
    at_step(pilot, "issue")
    message(pilot, "park #7")
    assert pilot.state["park"] == "manuell"
    assert pilot.texts() == ["#7 wird nach dem Schritt geparkt"]


def test_stop_stops_the_fork_and_parks(pilot):
    at_step(pilot, "issue")
    pilot.result("autopilot-poll.py", "next", out="")
    assert message(pilot, "stop #7") == [{"stop": "t1"}]
    assert not pilot.ran("leave-branch.py")
    assert pilot.state["parked"] == []
    assert pilot.event("stopped", "t1") == [
        {
            "background": "autopilot-task.py poller autopilot-poll.py wait new_issue ready answer 7 2026-01-01T00:00:00Z",
            "timeout": pilot.module.BACKGROUND_MS,
        }
    ]
    assert pilot.ran("leave-branch.py", "issue-7-fix-the-thing")
    entry = pilot.state["parked"][0]
    assert entry["reason"] == "abgebrochen"
    assert entry["step"] == "issue"


def test_park_of_another_issue(pilot):
    at_step(pilot, "issue", parked=[parked()])
    message(pilot, "park #9")
    message(pilot, "park #4")
    assert pilot.texts() == ["#4 ist schon geparkt"]


def test_park_during_the_merge_wait_is_refused(pilot):
    at_merge_ci(pilot)
    assert message(pilot, "stop #7") == []
    assert pilot.texts() == ["#7 ist gemergt, Merge wird abgeschlossen"]
    assert pilot.state["parked"] == []


def test_answer_for_a_parked_issue(pilot):
    at_step(pilot, "issue", parked=[parked()])
    message(pilot, "#4 a")
    assert pilot.ran("gh", "issue", "comment", "4")
    assert pilot.state["parked"][0]["answer"] == "a) x"


def test_recommendations_are_expanded(pilot):
    question = "1. A? Recommendation: yes\n2. B? Recommendation: no"
    at_step(pilot, "issue", parked=[parked(question=question)])
    message(pilot, "#4 Empfehlungen")
    assert pilot.state["parked"][0]["answer"] == (
        "Empfehlungen übernehmen: 1. yes 2. no"
    )


def test_answer_without_a_current_issue_resumes_it(pilot):
    pilot.state = {"waiting_for": "new_issue", "parked": [parked()]}
    actions = message(pilot, "#4 b")
    assert actions[0] == {"skill": "pipeline:plan-issue", "args": '4 "b) y" ""'}


def test_answer_during_the_search_stops_it(pilot):
    at_step(pilot, "plan-issue", question=QUESTION, events_since="t0")
    actions = message(pilot, "#7 take x")
    assert actions[0] == {"stop": "t1"}
    assert actions[1] == {"skill": "pipeline:plan-issue", "args": '7 "take x" ""'}
    assert pilot.state["question"] is None


def test_answer_for_an_issue_that_waits_for_none(pilot):
    at_step(pilot, "issue")
    message(pilot, "#9 x")
    assert pilot.texts() == ["#9 wartet nicht auf eine Antwort"]


def test_restart_state_answers_only_some_commands(pilot):
    pilot.state = {"waiting_for": "restart"}
    message(pilot, "weiter")
    assert pilot.texts() == ["Autopilot braucht einen Neustart"]


def test_cleanup_secures_the_tree(pilot):
    pilot.state = {"paused": True, "waiting_for": "resume"}
    pilot.result("git", "branch", "--show-current", out="issue-7-x")
    pilot.result("cleanup-tree.py", out="cleanup-7-1")
    message(pilot, "cleanup")
    assert pilot.texts() == ["#7 Änderungen auf cleanup-7-1 gesichert, nicht gepusht"]


def test_cleanup_without_an_issue_branch(pilot):
    pilot.state = {"paused": True, "waiting_for": "resume"}
    message(pilot, "cleanup")
    assert pilot.texts() == ["Kein Issue-Branch, bitte von Hand aufräumen"]


@pytest.mark.parametrize("command", ["update", "rollback"])
def test_update_runs_the_update_script(pilot, command):
    pilot.state = {"waiting_for": "new_issue"}
    pilot.result(
        f".claude/skills/pipeline/host/{command}-pipeline.sh", out="x\nhttps://pr/9"
    )
    message(pilot, command)
    assert pilot.texts() == ["https://pr/9"]


def test_rollback_with_a_current_issue_is_refused(pilot):
    at_step(pilot, "issue", waiting_for="resume", paused=True, task_id=None)
    message(pilot, "rollback")
    assert pilot.texts() == ["rollback nur ohne aktuelles Issue"]


def test_update_with_a_current_issue_is_refused(pilot):
    at_step(pilot, "issue", waiting_for="resume", paused=True, task_id=None)
    message(pilot, "update")
    assert pilot.texts() == ["update nur ohne aktuelles Issue"]


# Task commands


def test_task_starts_a_step_for_any_issue(pilot):
    pilot.state = {"paused": True, "waiting_for": "resume"}
    pilot.result(
        "issue-pr.py",
        out=json.dumps(
            {"state": "OPEN", "pr": 8, "branch": "issue-9-y", "review_rounds": 2}
        ),
    )
    pilot.result("gh", "pr", "view", "8", "--json", "headRefOid", out="d" * 40)
    actions = message(pilot, "/review-issue 9")
    assert pilot.ran("git", "fetch", "origin", "issue-9-y")
    assert pilot.state["issue"] == 9
    assert pilot.state["pr"] == 8
    assert pilot.state["review_rounds"] == 2
    assert pilot.state["paused"] is False
    assert actions[0]["background"].endswith(f"watch-ci.py issue-9-y {'d' * 40}")


def test_task_without_a_pull_request(pilot):
    pilot.state = {"paused": True, "waiting_for": "resume"}
    message(pilot, "/fix-review 9")
    assert pilot.texts() == ["#9 kein PR, /fix-review nicht gestartet"]
    assert pilot.state["issue"] is None


def test_task_of_a_closed_issue(pilot):
    pilot.state = {"paused": True, "waiting_for": "resume"}
    pilot.result(
        "issue-pr.py",
        out=json.dumps(
            {"state": "CLOSED", "pr": None, "branch": None, "review_rounds": 0}
        ),
    )
    message(pilot, "/issue 9")
    assert pilot.texts() == ["#9 ist geschlossen"]


def test_task_parks_the_current_issue(pilot):
    at_step(pilot, "issue", paused=True, waiting_for="resume", task_id=None)
    pilot.result("gh", "issue", "view", "9", out="Other")
    actions = message(pilot, "/plan-issue 9")
    assert pilot.state["parked"][0]["issue"] == 7
    assert pilot.state["parked"][0]["reason"] == "manuell"
    assert pilot.state["issue"] == 9
    assert actions == [{"skill": "pipeline:plan-issue", "args": '9 "" ""'}]
    switches = [call for call in pilot.calls if call[:2] == ("git", "switch")]
    assert switches[-1] == ("git", "switch", "issue-9-other")


def test_task_only_while_paused(pilot):
    message(pilot, "/issue 9")
    assert pilot.texts() == [pilot.module.PAUSED]


def test_steps_are_skills_of_the_plugin(pilot):
    steps = {*pilot.module.STEP_LABELS, "setprio", "find-answer"} - {"review-issue"}
    assert all((ROOT / "skills" / step / "SKILL.md").exists() for step in steps)


def test_failed_command_keeps_the_state_and_pauses(pilot):
    at_step(pilot, "fix-review", paused=True, waiting_for="resume", task_id=None)
    pilot.result("git", "pull", code=1, err="not a fast-forward")
    assert message(pilot, "weiter") == []
    assert pilot.texts() == ["#7 Fehler: not a fast-forward, nach Behebung weiter"]
    assert pilot.state["paused"] is True
    assert pilot.state["step"] == "fix-review"


def test_dirty_branch_is_not_left(pilot):
    pilot.state = {"parked": [parked(answer="x")]}
    pilot.result("leave-branch.py", code=1, out="dirty")
    pilot.event("start", "")
    assert pilot.sent[0][1] == ("cleanup", "status")
    assert not pilot.ran("git", "switch", "issue-4-x")
    assert pilot.state["paused"] is True
    assert pilot.state["parked"][0]["answer"] == "x"


def test_update_restarts_on_a_new_release(pilot):
    pilot.state = {"waiting_for": "new_issue"}
    pilot.result("release-changed.sh", out="v3")
    message(pilot, "update")
    assert pilot.ran("autopilot-restart.sh")
    assert not pilot.ran(".claude/skills/pipeline/host/update-pipeline.sh")


def test_answer_while_paused_is_only_stored(pilot):
    pilot.state = {"paused": True, "waiting_for": "resume", "parked": [parked()]}
    assert message(pilot, "#4 a") == []
    assert pilot.state["parked"][0]["answer"] == "a) x"
    assert pilot.state["issue"] is None


def test_weiter_with_a_pending_wait_starts_the_poller(pilot):
    pilot.state = {"paused": True, "waiting_for": "new_issue"}
    actions = message(pilot, "weiter")
    assert actions[0]["background"].startswith("autopilot-task.py poller")
    assert not pilot.ran("autopilot-poll.py", "next")


def test_label_while_paused_keeps_the_wait(pilot):
    pilot.state = {"paused": True, "waiting_for": "new_issue"}
    assert message(pilot, "label next") == []
    assert pilot.texts() == ["Label next"]
    assert pilot.state["waiting_for"] == "new_issue"


def test_task_resumes_a_parked_entry(pilot):
    pilot.state = {
        "paused": True,
        "waiting_for": "resume",
        "parked": [parked(pr=6, review_rounds=3)],
    }
    actions = message(pilot, "/fix-review 4")
    assert pilot.ran("git", "switch", "issue-4-x")
    assert pilot.ran("git", "pull", "--ff-only", "origin", "issue-4-x")
    assert pilot.state["parked"] == []
    assert pilot.state["step"] == "fix-review"
    assert pilot.state["review_rounds"] == 3
    assert actions[0]["skill"] == "pipeline:fix-review"


def test_cleanup_with_nothing_to_secure(pilot):
    pilot.state = {"paused": True, "waiting_for": "resume"}
    pilot.result("git", "branch", "--show-current", out="issue-7-x")
    pilot.result("cleanup-tree.py", out="clean", code=1)
    message(pilot, "cleanup")
    assert pilot.texts() == ["#7 Nichts zu sichern"]


def test_log_lines(pilot, tmp_path):
    at_step(pilot, "plan-issue", verbose=True)
    finish(pilot, result())
    log = (tmp_path / "autopilot.log").read_text().splitlines()
    assert log[-1].endswith(" #7 issue start")
    assert "#7 issue start" in pilot.texts()


def test_main_writes_the_state_atomically_and_prints_actions(
    pilot, tmp_path, monkeypatch, capsys
):
    module = pilot.module
    monkeypatch.setattr(module.Autopilot, "run", pilot.run)
    monkeypatch.setattr(module.sys, "stdin", type("S", (), {"read": lambda self: ""})())
    module.main(["event", "start"])
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["step"] == "plan-issue"
    assert not (tmp_path / "state.json.tmp").exists()
    assert json.loads(capsys.readouterr().out)["skill"] == "pipeline:plan-issue"


def test_main_rejects_unknown_events(pilot):
    with pytest.raises(SystemExit):
        pilot.module.main(["event", "nope"])


# Transitions while held, failures inside events


def test_failed_release_check_is_reported_and_goes_on(pilot):
    pilot.result("release-changed.sh", code=1, err="no tag")
    actions = pilot.event("start", "")
    assert pilot.texts()[0] == "Release-Prüfung fehlgeschlagen: no tag"
    assert actions[0]["skill"] == "pipeline:plan-issue"


@pytest.mark.parametrize(("code", "paused"), [(0, False), (1, True)])
def test_pipeline_repository_switches_to_the_release(
    pilot, tmp_path, monkeypatch, code, paused
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "pipeline-release").write_text("v2\n")
    pilot.result("release-changed.sh", out="v2")
    pilot.result(".claude/skills/pipeline/host/use-release.sh", code=code, err="bad")
    pilot.event("start", "")
    assert pilot.ran("autopilot-restart.sh") is not paused
    assert pilot.state["paused"] is paused
    if paused:
        assert pilot.texts() == ["bad"]


def test_found_answer_with_a_pending_park_parks_without_it(pilot):
    at_step(pilot, "plan-issue", question=QUESTION, events_since="t0", park="manuell")
    pilot.result("autopilot-poll.py", "next", out="")
    finish(pilot, result(summary="use x"))
    entry = pilot.state["parked"][0]
    assert (entry["reason"], entry["answer"]) == ("manuell", None)


def test_found_answer_while_paused_parks_with_it(pilot):
    at_step(pilot, "plan-issue", question=QUESTION, events_since="t0", paused=True)
    assert finish(pilot, result(summary="use x")) == []
    entry = pilot.state["parked"][0]
    assert (entry["reason"], entry["answer"]) == ("Rückfrage", "use x")


@pytest.mark.parametrize(
    ("held", "reason"),
    [({"park": "manuell"}, "manuell"), ({"paused": True}, "Rückfrage")],
)
def test_maintainer_comment_while_held_parks_with_it(pilot, held, reason):
    at_step(pilot, "plan-issue", question=QUESTION, events_since="t0", **held)
    pilot.result("autopilot-poll.py", "next", out="")
    pilot.result(
        "autopilot-poll.py",
        "check",
        out=json.dumps({"type": "comment", "number": 7, "body": "b"}),
    )
    actions = finish(pilot, result("needs_input"))
    assert f"park {reason}" in (pilot.folder / "autopilot.log").read_text()
    if "paused" in held:
        entry = pilot.state["parked"][0]
        assert (entry["reason"], entry["answer"]) == (reason, "b")
    else:
        # The answered entry resumes at once, at the next issue boundary.
        assert actions == [{"skill": "pipeline:plan-issue", "args": '7 "b" ""'}]


def test_answer_for_the_current_issue_while_paused_parks_it(pilot):
    at_step(pilot, "plan-issue", question=QUESTION, events_since="t0", paused=True)
    actions = message(pilot, "#7 a")
    assert actions == [{"stop": "t1"}]
    entry = pilot.state["parked"][0]
    assert (entry["reason"], entry["answer"]) == ("Rückfrage", "a) x")


def test_setprio_done_with_a_pending_park_parks(pilot):
    at_step(pilot, "setprio", branch=None, pr=None, park="manuell")
    pilot.result("autopilot-poll.py", "next", out="")
    finish(pilot, result())
    assert pilot.state["parked"][0]["step"] == "setprio"
    assert "ready" not in pilot.labels()


def test_third_failure_while_paused_parks_and_waits(pilot):
    at_step(pilot, "issue", attempts=2, paused=True)
    assert finish(pilot, result("blocked", summary="broken")) == []
    assert pilot.state["parked"][0]["reason"] == "Fehlversuche"
    assert pilot.state["waiting_for"] == "resume"


def test_fifth_review_round_while_paused_parks_and_waits(pilot):
    at_step(pilot, "review-issue", review_rounds=4, paused=True)
    assert finish(pilot, out=result(verdict="changes requested", summary="o")) == []
    assert pilot.state["parked"][0]["reason"] == "Review-Limit"
    assert "#7 Review-Limit erreicht, offene Befunde: o" in pilot.texts()


def test_patch_while_paused_parks_and_waits(pilot):
    at_step(pilot, "issue", paused=True)
    assert finish(pilot, result("needs_input", patch="https://c/2")) == []
    assert pilot.state["parked"][0]["waiting_for"] == "patch"


def test_review_without_a_verdict_is_a_failure(pilot):
    at_step(pilot, "review-issue")
    actions = finish(pilot, out=result())
    assert pilot.state["failure"] == "Kein Verdict: s"
    assert actions[0]["background"].endswith(
        f"watch-ci.py issue-7-fix-the-thing {'a' * 40}"
    )


def test_open_review_threads_name_the_threads_at_the_limit(pilot):
    at_ci(pilot, review_rounds=4)
    pilot.result("open-review-threads.py", out=json.dumps([{"url": "https://t/1"}]))
    pilot.result("autopilot-poll.py", "next", out="")
    finish(pilot, out="green", code=0)
    assert "#7 Review-Limit erreicht, offene Befunde: https://t/1" in pilot.texts()


def test_resume_without_a_known_pull_request_looks_it_up(pilot):
    pilot.state = {"parked": [parked(answer="a", step="issue")]}
    pilot.result(
        "issue-pr.py",
        out=json.dumps({"state": "OPEN", "pr": 6, "branch": "issue-4-x"}),
    )
    pilot.event("start", "")
    assert pilot.ran("git", "pull", "--ff-only", "origin", "issue-4-x")
    assert pilot.state["pr"] == 6


def test_resume_after_a_patch_pulls_the_commit(pilot):
    pilot.state = {"parked": [parked(waiting_for="patch", reason="Patch")]}
    pilot.result(
        "autopilot-poll.py",
        "check",
        out=json.dumps({"type": "commit", "branch": "issue-4-x"}),
    )
    actions = pilot.event("start", "")
    assert pilot.ran("git", "pull", "--ff-only", "origin", "issue-4-x")
    assert actions[0]["args"] == '4 "Der Maintainer hat den Patch committet." ""'


def test_cleanup_only_while_paused(pilot):
    message(pilot, "cleanup")
    assert pilot.texts() == ["cleanup nur in der Pause"]


def test_failed_cleanup_is_reported(pilot):
    pilot.state = {"paused": True, "waiting_for": "resume"}
    pilot.result("git", "branch", "--show-current", out="issue-7-x")
    pilot.result("cleanup-tree.py", code=1, err="no identity")
    message(pilot, "cleanup")
    assert pilot.texts() == ["#7 cleanup fehlgeschlagen: no identity"]


def test_update_on_a_dirty_tree_is_refused(pilot):
    pilot.state = {"waiting_for": "new_issue"}
    pilot.result("git", "status", "--porcelain", out=" M a.py")
    message(pilot, "update")
    assert pilot.sent == [(pilot.module.DIRTY, ("cleanup", "status"))]
    assert not pilot.ran("release-changed.sh")


def test_update_while_a_step_runs_is_refused(pilot):
    pilot.state = {"waiting_for": None, "paused": True}
    message(pilot, "update")
    assert pilot.texts() == ["update nur ohne aktuelles Issue"]


def test_weiter_when_not_paused(pilot):
    pilot.state = {"waiting_for": "new_issue"}
    message(pilot, "weiter")
    assert pilot.texts() == ["Läuft bereits"]


def test_failed_command_in_a_done_event_is_repeated_by_weiter(pilot):
    at_step(pilot, "issue")
    pilot.result("gh", "pr", "list", code=1, err="api down")
    assert finish(pilot, text=result()) == []
    assert pilot.texts() == ["#7 Fehler: api down, nach Behebung weiter"]
    assert pilot.state["paused"] is True
    assert pilot.state["waiting_for"] == "resume"
    assert pilot.state["step"] == "issue"
    pilot.result("gh", "pr", "list", out="5")
    actions = message(pilot, "weiter")
    assert pilot.state["retry"] is None
    assert pilot.state["waiting_for"] == "review_ci"
    assert pilot.state["paused"] is False
    assert actions[0]["background"].endswith(
        f"watch-ci.py issue-7-fix-the-thing {'a' * 40}"
    )


def test_failed_command_after_the_merge_wait_records_once(pilot):
    at_merge_ci(pilot)
    pilot.result("gh", "issue", "view", "7", "--json", "state", code=1, err="down")
    finish(pilot, out="green", code=0)
    assert not pilot.ran("pipeline-metrics.py")
    pilot.result("gh", "issue", "view", "7", "--json", "state", out="OPEN")
    pilot.result("autopilot-poll.py", "next", out="")
    message(pilot, "weiter")
    assert pilot.ran("pipeline-metrics.py", "record")
    assert pilot.state["issue"] is None


def test_failed_command_in_a_restart_is_repeated_by_weiter(pilot):
    at_step(pilot, "review-issue")
    pilot.result("gh", "pr", "view", "5", "--json", "headRefOid", code=1, err="down")
    assert pilot.event("start", "") == []
    assert pilot.state["waiting_for"] == "resume"
    pilot.result("gh", "pr", "view", "5", "--json", "headRefOid", out="a" * 40)
    actions = message(pilot, "weiter")
    assert actions[0]["background"].endswith(
        f"watch-ci.py issue-7-fix-the-thing {'a' * 40}"
    )


def test_unexpected_error_keeps_the_state_and_pauses(pilot):
    at_step(pilot, "issue")
    pilot.result("gh", "pr", "list", out="five")
    assert finish(pilot, text=result()) == []
    assert pilot.texts()[0].startswith("#7 Fehler: ValueError ")
    assert pilot.state["step"] == "issue"
    assert pilot.state["paused"] is True


def test_poller_ended_by_a_signal_starts_again(pilot):
    pilot.state = {"waiting_for": "new_issue", "poller": "p1"}
    pilot.task("poller", "", code=-15)
    actions = pilot.event("done", "p1")
    assert actions[0]["background"].startswith("autopilot-task.py poller")
    assert pilot.state["poll_failures"] == 0


def test_start_does_not_kill_a_stale_poller_pid(pilot, tmp_path, monkeypatch):
    killed = []
    monkeypatch.setattr(pilot.module.os, "kill", lambda *a: killed.append(a))
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "poller.pid").write_text("123\n")
    pilot.state = {"waiting_for": "new_issue", "poller": "p1"}
    pilot.event("start", "")
    message(pilot, "status")
    assert killed == []
    assert not (tmp_path / "tasks" / "poller.pid").exists()


def test_stopped_task_that_already_ended_is_ignored(pilot):
    at_step(pilot, "issue", park="abgebrochen")
    pilot.result("autopilot-poll.py", "next", out="")
    finish(pilot, text=result())
    assert pilot.state["parked"][0]["reason"] == "abgebrochen"
    assert pilot.event("stopped", "t1") == []


def test_failed_command_while_parking_a_stopped_task_is_repeated(pilot):
    at_step(pilot, "issue")
    message(pilot, "stop #7")
    pilot.result("autopilot-poll.py", "now", code=1, err="api down")
    assert pilot.event("stopped", "t1") == []
    assert pilot.state["waiting_for"] == "resume"
    pilot.result("autopilot-poll.py", "now", out="2026-01-01T00:00:00Z")
    pilot.result("autopilot-poll.py", "next", out="")
    message(pilot, "weiter")
    assert pilot.state["parked"][0]["reason"] == "abgebrochen"


@pytest.mark.parametrize("command", ["park #7", "/issue 7"])
def test_retry_ends_when_the_issue_leaves_the_error_pause(pilot, command):
    at_step(pilot, "issue")
    pilot.result("gh", "pr", "list", code=1, err="api down")
    finish(pilot, text=result())
    assert pilot.state["retry"]
    pilot.result("autopilot-poll.py", "next", out="")
    message(pilot, command)
    assert pilot.state["retry"] is None


@pytest.mark.parametrize(
    ("moved", "out"),
    [(("git", "rev-parse", "HEAD"), "d" * 40), (("git", "ls-remote"), "new")],
)
def test_commit_or_push_in_a_read_only_step_is_blocked(pilot, moved, out):
    at_step(pilot, "plan-issue", refs=["c" * 40, ""])
    pilot.result(*moved, out=out)
    assert finish(pilot, result()) == []
    assert pilot.sent == [
        (
            (
                "#7 plan-issue blockiert: Commit oder Push in einem lesenden Schritt "
                "(oder ein Push auf issue-7-fix-the-thing), bitte prüfen; weiter setzt fort "
                "und pusht beim Parken, was auf dem Branch liegt"
            ),
            ("status",),
        )
    ]
    assert pilot.state["step"] == "plan-issue"
    assert pilot.state["paused"] is True
    assert pilot.state["refs"] is None
    assert not pilot.ran("leave-branch.py")
    actions = message(pilot, "weiter")
    assert actions[0]["skill"] == "pipeline:plan-issue"
    # The step starts again from the state the maintainer left.
    assert pilot.state["refs"] is not None


def test_unchanged_refs_let_a_read_only_step_pass(pilot):
    at_step(pilot, "plan-issue", refs=["c" * 40, ""])
    finish(pilot, result())
    assert pilot.state["step"] == "issue"
    assert pilot.state["refs"] is None


def test_blocked_search_is_reported_and_searches_again(pilot):
    at_step(
        pilot, "plan-issue", question=QUESTION, events_since="t0", refs=["c" * 40, ""]
    )
    pilot.result("git", "rev-parse", "HEAD", out="d" * 40)
    pilot.result(
        "autopilot-poll.py",
        "check",
        out=json.dumps({"type": "comment", "number": 7, "body": "b"}),
    )
    assert finish(pilot, result(summary="use x")) == []
    assert pilot.texts()[0].startswith("#7 find-answer blockiert")
    assert not pilot.ran("gh", "issue", "comment", "7")
    actions = message(pilot, "weiter")
    assert actions[0]["skill"] == "pipeline:find-answer"
    assert pilot.state["events_since"] == "t0"


def test_rerun_and_restart_keep_the_refs(pilot):
    at_step(pilot, "plan-issue", refs=["c" * 40, ""])
    pilot.result("git", "rev-parse", "HEAD", out="d" * 40)
    pilot.event("start", "")
    assert pilot.state["refs"] == ["c" * 40, ""]


def test_stop_of_a_read_only_step_that_committed_does_not_park(pilot):
    at_step(pilot, "plan-issue", refs=["c" * 40, ""])
    message(pilot, "stop #7")
    pilot.result("git", "rev-parse", "HEAD", out="d" * 40)
    pilot.event("stopped", "t1")
    assert not pilot.ran("leave-branch.py")
    assert pilot.state["paused"] is True
    assert pilot.state["park"] == "abgebrochen"


def test_start_of_a_read_only_step_stores_the_refs(pilot):
    pilot.result("git", "ls-remote", out="r")
    pilot.event("start", "")
    assert pilot.state["refs"] == ["c" * 40, "r"]


def test_search_stores_the_refs(pilot):
    at_step(pilot, "issue")
    finish(pilot, result("needs_input", open_questions=QUESTION))
    assert pilot.state["refs"] == ["c" * 40, ""]


def test_restart_with_a_merged_pull_request_finishes_the_merge(pilot):
    at_step(pilot, "review-issue")
    pilot.result("gh", "pr", "view", "5", "--json", "state", out="MERGED")
    actions = pilot.event("start", "")
    assert not pilot.ran("gate")
    assert pilot.ran("git", "switch", "main")
    assert pilot.state["merge"] == {"default": "main", "sha": "m" * 40}
    assert actions == [
        {
            "background": f"autopilot-task.py step watch-ci.py main {'m' * 40}",
            "timeout": pilot.module.BACKGROUND_MS,
        }
    ]
    pilot.event("started", "t2")
    pilot.result("autopilot-poll.py", "next", out="")
    pilot.task("step", "green", code=0)
    pilot.event("done", "t2")
    assert pilot.ran("gh", "issue", "close", "7")
    assert "#7 fertig: https://pr/5" in pilot.texts()
    assert pilot.state["issue"] is None


def test_repeated_merge_after_a_failure_does_not_merge_again(pilot):
    at_ci(pilot)
    pilot.result("gh", "pr", "view", "5", "--json", "state", out="MERGED")
    finish(pilot, out="green", code=0)
    assert not pilot.ran("gate", "merge")
    assert pilot.state["waiting_for"] == "merge_ci"


def test_restart_with_a_pending_park_checks_the_refs(pilot):
    at_step(pilot, "plan-issue", park="manuell", refs=["c" * 40, ""])
    pilot.result("git", "rev-parse", "HEAD", out="d" * 40)
    assert pilot.event("start", "") == []
    assert not pilot.ran("leave-branch.py")
    assert pilot.texts()[0].startswith("#7 plan-issue blockiert")
    assert pilot.state["paused"] is True


def test_setprio_without_need_for_a_plan_skips_plan_issue(pilot):
    at_step(pilot, "setprio", branch=None, pr=None, issue=7)
    actions = finish(pilot, result(plan="skip"))
    assert pilot.state["step"] == "issue"
    assert pilot.state["plan_skip"] == []
    assert actions[0]["skill"] == "pipeline:issue"


def test_setprio_with_need_for_a_plan_plans(pilot):
    at_step(pilot, "setprio", branch=None, pr=None, issue=7)
    actions = finish(pilot, result(plan="needed"))
    assert actions[0]["skill"] == "pipeline:plan-issue"


def test_red_ci_goes_to_fix_review_without_a_review(pilot):
    at_review_ci(pilot)
    actions = finish(pilot, out="red https://github.com/o/app/actions/runs/31", code=1)
    assert not pilot.ran("gate", "review")
    assert pilot.state["step"] == "fix-review"
    assert pilot.state["review_rounds"] == 1
    assert pilot.state["failure"] == (
        "CI rot: https://github.com/o/app/actions/runs/31"
        " (Log: gh run view 31 --log-failed)"
    )
    assert actions[0]["skill"] == "pipeline:fix-review"
    assert "gh run view 31 --log-failed" in actions[0]["args"]


def test_red_ci_counts_as_a_review_round_up_to_the_limit(pilot):
    at_review_ci(pilot, review_rounds=4)
    pilot.result("autopilot-poll.py", "next", out="")
    finish(pilot, out="red https://run/3", code=1)
    entry = pilot.state["parked"][0]
    assert entry["reason"] == "Review-Limit"
    assert entry["failure"].startswith("CI rot: https://run/3")


def test_resumed_fix_review_after_red_ci_gets_the_run(pilot):
    pilot.state = {
        "parked": [
            parked(answer="weiter", step="fix-review", failure="CI rot: https://run/3")
        ]
    }
    actions = pilot.event("start", "")
    assert actions[0]["args"] == '4 "weiter" "CI rot: https://run/3"'


def test_missing_ci_before_the_review_is_a_failure(pilot):
    at_review_ci(pilot)
    actions = finish(pilot, out="missing", code=1)
    assert pilot.state["step"] == "review-issue"
    assert pilot.state["failure"] == "kein CI-Lauf gefunden"
    assert actions[0]["background"].startswith("autopilot-task.py step watch-ci.py")


def test_restart_starts_the_ci_wait_before_the_review_again(pilot):
    at_review_ci(pilot)
    actions = pilot.event("start", "")
    assert actions[0]["background"].endswith(
        f"watch-ci.py issue-7-fix-the-thing {'a' * 40}"
    )
    assert pilot.state["waiting_for"] == "review_ci"


def test_green_ci_before_the_review_during_a_pause_waits(pilot):
    at_review_ci(pilot, paused=True)
    assert finish(pilot, out="green", code=0) == []
    assert not pilot.ran("gate", "review")
    assert pilot.state["waiting_for"] == "resume"


@pytest.mark.parametrize("held", [{"paused": True}, {"park": "manuell"}])
def test_review_after_a_hold_waits_for_ci_first(pilot, held):
    at_step(pilot, "fix-review", **held)
    pilot.result("autopilot-poll.py", "next", out="")
    finish(pilot, result())
    entry = pilot.state["parked"][0] if "park" in held else pilot.state
    assert entry["step"] == "review-issue"
    if "paused" in held:
        actions = message(pilot, "weiter")
        assert actions[0]["background"].startswith("autopilot-task.py step watch-ci.py")


def test_stop_during_the_ci_wait_parks_the_review(pilot):
    at_review_ci(pilot)
    pilot.result("autopilot-poll.py", "next", out="")
    message(pilot, "stop #7")
    pilot.event("stopped", "t1")
    assert pilot.state["parked"][0]["step"] == "review-issue"


def test_issue_without_a_pull_request_is_a_failure(pilot):
    at_step(pilot, "issue", pr=None)
    pilot.result("gh", "pr", "list", out="")
    finish(pilot, result())
    assert pilot.state["failure"] == "Kein Pull Request zum Branch"


# Merge of the default branch


def test_mergeable_pull_request_skips_the_default_branch(pilot):
    at_step(pilot, "review-issue")
    pilot.result("gh", "pr", "view", "5", "--json", "mergeable", out="MERGEABLE")
    pilot.result(
        "gh",
        "api",
        "repos/{owner}/{repo}/rules/branches/main?per_page=100",
        out="false",
    )
    actions = finish(pilot, out=result(verdict="approve"))
    assert not pilot.ran("merge-default-branch.py")
    assert pilot.state["waiting_for"] == "ci"
    assert actions[0]["background"].startswith("autopilot-task.py step sh -c")


def test_required_up_to_date_branch_merges_the_default_branch(pilot):
    at_step(pilot, "review-issue")
    pilot.result("gh", "pr", "view", "5", "--json", "mergeable", out="MERGEABLE")
    pilot.result(
        "gh", "api", "repos/{owner}/{repo}/rules/branches/main?per_page=100", out="true"
    )
    finish(pilot, out=result(verdict="approve"))
    assert pilot.ran("merge-default-branch.py")


def test_carried_approve_waits_for_ci_without_a_review(pilot):
    at_step(pilot, "review-issue")
    pilot.result("merge-default-branch.py", out="merged")
    actions = finish(pilot, out=result(verdict="approve"))
    assert pilot.ran("gate", "carry", "5", "c" * 40)
    assert pilot.state["sync_rounds"] == 1
    assert pilot.state["waiting_for"] == "ci"
    assert actions[0]["background"].startswith("autopilot-task.py step sh -c")


def test_too_many_merges_of_the_default_branch_park(pilot):
    at_step(pilot, "review-issue", sync_rounds=3)
    pilot.result("merge-default-branch.py", out="merged")
    pilot.result("autopilot-poll.py", "next", out="")
    finish(pilot, out=result(verdict="approve"))
    assert pilot.ran("git", "push", "origin", "issue-7-fix-the-thing")
    assert not pilot.ran("gate", "carry")
    entry = pilot.state["parked"][0]
    assert entry["reason"] == "Default-Branch zu oft nachgezogen"
    assert entry["step"] == "review-issue"


@pytest.mark.parametrize("mergeable", ["CONFLICTING", "UNKNOWN"])
def test_not_mergeable_pull_request_merges_the_default_branch(pilot, mergeable):
    at_step(pilot, "review-issue")
    pilot.result("gh", "pr", "view", "5", "--json", "mergeable", out=mergeable)
    finish(pilot, out=result(verdict="approve"))
    assert pilot.ran("merge-default-branch.py")
    assert not pilot.ran("gh", "api")


def test_fix_review_after_red_ci_may_commit(pilot):
    at_step(pilot, "fix-review")
    finish(pilot, result())
    assert pilot.state["refs"] is None
    pilot.event("started", "t1")
    pilot.task("step", "red https://run/3", code=1)
    finish(pilot)
    pilot.event("started", "t1")
    pilot.result("git", "rev-parse", "HEAD", out="d" * 40)
    actions = finish(pilot, result())
    assert pilot.state["paused"] is False
    assert actions[0]["background"].startswith("autopilot-task.py step watch-ci.py")


def test_green_ci_records_the_refs_for_the_review(pilot):
    at_review_ci(pilot)
    finish(pilot, out="green", code=0)
    assert pilot.state["refs"] == ["c" * 40, ""]


@pytest.mark.parametrize(("plan", "kept"), [("needed", []), ("skip", [7])])
def test_latest_setprio_decides_the_plan(pilot, plan, kept):
    at_step(pilot, "setprio", branch=None, pr=None, issue=7, plan_skip=[7])
    pilot.result("autopilot-poll.py", "next", out="")
    finish(pilot, result(plan=plan))
    assert pilot.state["plan_skip"] == kept


# Budget


def test_issue_budget_parks_the_issue(pilot):
    at_step(pilot, "plan-issue", fork_runs=15)
    pilot.result("autopilot-poll.py", "next", out="")
    actions = finish(pilot, result())
    assert pilot.sent[0] == (
        "#7 geparkt, Budget erreicht: 15 Fork-Läufe",
        ("#7 weiter", "status"),
    )
    assert "#7 geparkt (Budget)" not in pilot.texts()
    assert pilot.state["parked"][0]["reason"] == "Budget"
    assert pilot.state["parked"][0]["fork_runs"] == 15
    assert not any("skill" in action for action in actions)


def test_each_started_step_counts_for_the_issue_and_the_day(pilot):
    at_step(pilot, "plan-issue", fork_runs=3, day=pilot.module.now()[:10], day_forks=9)
    finish(pilot, result())
    assert pilot.state["fork_runs"] == 4
    assert pilot.state["day_forks"] == 10


def test_day_budget_pauses_and_weiter_grants_more(pilot):
    at_step(pilot, "plan-issue", day=pilot.module.now()[:10], day_forks=50)
    actions = finish(pilot, result())
    assert pilot.sent[-1] == (
        "Tagesbudget erreicht: 50 Fork-Läufe heute, weiter gibt 50 weitere frei",
        ("weiter", "status"),
    )
    assert pilot.state["paused"] is True
    assert pilot.state["step"] == "issue"
    assert not any("skill" in action for action in actions)
    actions = pilot.event("telegram", "1", text="weiter")
    assert actions[0]["skill"] == "pipeline:issue"
    assert pilot.state["day_forks"] == 1


def test_day_budget_starts_again_on_a_new_day(pilot):
    at_step(pilot, "plan-issue", day="2000-01-01", day_forks=50)
    actions = finish(pilot, result())
    assert actions[0]["skill"] == "pipeline:issue"
    assert pilot.state["day"] == pilot.module.now()[:10]
    assert pilot.state["day_forks"] == 1


@pytest.mark.parametrize("reason", ["Budget", "Rückfrage"])
def test_resumed_park_gets_a_new_budget(pilot, reason):
    pilot.state = {
        "parked": [parked(reason=reason, fork_runs=15, question=None)],
    }
    pilot.result(
        "autopilot-poll.py",
        "check",
        out=json.dumps({"type": "comment", "number": 4, "body": "go on"}),
    )
    actions = pilot.event("start", "")
    assert actions[0]["skill"] == "pipeline:plan-issue"
    assert pilot.state["fork_runs"] == 1


def today(pilot):
    return pilot.module.now()[:10]


def test_day_budget_keeps_the_answer_of_a_resume(pilot):
    pilot.state = {
        "parked": [parked(question=None)],
        "day": today(pilot),
        "day_forks": 50,
    }
    pilot.result(
        "autopilot-poll.py",
        "check",
        out=json.dumps({"type": "comment", "number": 4, "body": "take a"}),
    )
    pilot.event("start", "")
    assert pilot.state["paused"] is True
    actions = pilot.event("telegram", "1", text="weiter")
    assert actions[0] == {"skill": "pipeline:plan-issue", "args": '4 "take a" ""'}
    assert pilot.state["held_answer"] is None


def test_day_budget_keeps_a_telegram_answer(pilot):
    at_step(pilot, "plan-issue", question=QUESTION, events_since="t0")
    pilot.state.update(day=today(pilot), day_forks=50)
    pilot.event("telegram", "1", text="#7 take x")
    assert pilot.state["paused"] is True
    actions = pilot.event("telegram", "1", text="weiter")
    assert actions[0] == {"skill": "pipeline:plan-issue", "args": '7 "take x" ""'}


def test_day_budget_keeps_a_found_answer(pilot):
    at_step(pilot, "plan-issue", question=QUESTION, events_since="t0")
    pilot.state.update(day=today(pilot), day_forks=50)
    finish(pilot, result(summary="use x"))
    assert pilot.state["paused"] is True
    actions = pilot.event("telegram", "1", text="weiter")
    assert actions[0] == {"skill": "pipeline:plan-issue", "args": '7 "use x" ""'}


def test_park_during_the_day_budget_keeps_the_answer(pilot):
    at_step(pilot, "plan-issue", question=QUESTION, events_since="t0")
    pilot.state.update(day=today(pilot), day_forks=50)
    pilot.event("telegram", "1", text="#7 take x")
    pilot.result("autopilot-poll.py", "next", out="")
    pilot.event("telegram", "1", text="park #7")
    assert pilot.state["parked"][0]["held_answer"] == "take x"
    assert pilot.state["parked"][0]["answer"] is None


def test_answer_at_the_issue_budget_stays_parked(pilot):
    at_step(pilot, "plan-issue", question=QUESTION, events_since="t0", fork_runs=15)
    pilot.result("autopilot-poll.py", "next", out="")
    actions = finish(pilot, result(summary="use x"))
    entry = pilot.state["parked"][0]
    assert (entry["reason"], entry["answer"], entry["held_answer"]) == (
        "Budget",
        None,
        "use x",
    )
    assert not any("skill" in action for action in actions)
    pilot.result(
        "autopilot-poll.py",
        "check",
        out=json.dumps({"type": "comment", "number": 7, "body": "go on"}),
    )
    pilot.state = {"parked": pilot.state["parked"]}
    actions = pilot.event("start", "")
    assert actions[0]["args"] == '7 "use x" ""'


def test_find_answer_counts_for_the_budget(pilot):
    at_step(pilot, "plan-issue", fork_runs=2)
    finish(pilot, result("needs_input", open_questions=QUESTION))
    assert pilot.state["fork_runs"] == 3


def test_task_command_resume_gets_a_new_budget(pilot):
    pilot.state = {
        "paused": True,
        "waiting_for": "resume",
        "parked": [parked(pr=6, reason="Budget", fork_runs=15)],
    }
    message(pilot, "/fix-review 4")
    assert pilot.state["fork_runs"] == 1


# Usage and metrics


def test_done_counts_the_usage_of_the_step_fork(pilot):
    at_step(pilot, "issue")
    for _ in range(2):
        pilot.event("done", "t1", "1500", "61000", text=result("blocked"))
        pilot.event("started", "t1")

    assert pilot.state["usage"] == {
        "issue": {"forks": 2, "tokens": 3000, "duration_s": 122}
    }


def test_done_of_find_answer_counts_under_its_own_name(pilot):
    at_step(pilot, "plan-issue", question=QUESTION)
    pilot.event("done", "t1", "800", "30000", text=result(answer="none"))
    assert pilot.state["usage"]["find-answer"] == {
        "forks": 1,
        "tokens": 800,
        "duration_s": 30,
    }


def test_done_without_usage_counts_nothing(pilot):
    at_step(pilot, "issue")
    finish(pilot, result("blocked"))
    assert pilot.state["usage"] == {}


def test_park_records_metrics_and_keeps_the_usage(pilot):
    at_step(pilot, "issue", attempts=2, usage={"issue": {"forks": 2}})
    pilot.result("autopilot-poll.py", "next", out="")
    finish(pilot, result("blocked", summary="broken"))
    assert ("pipeline-metrics.py", "park", "Fehlversuche") in pilot.calls
    assert pilot.state["parked"][0]["usage"] == {"issue": {"forks": 2}}


def test_park_reports_failed_metrics(pilot):
    at_step(pilot, "issue", attempts=2)
    pilot.result("autopilot-poll.py", "next", out="")
    pilot.result("pipeline-metrics.py", "park", code=1, err="disk full")
    finish(pilot, result("blocked", summary="broken"))
    assert "#7 Kennzahlen nicht erfasst: disk full" in pilot.texts()


@pytest.mark.parametrize(
    "args",
    [["done", "t1", "12"], ["done", "t1", "x", "1"], ["started", "t1", "1", "2"]],
)
def test_main_rejects_wrong_usage_arguments(pilot, args):
    with pytest.raises(SystemExit):
        pilot.module.main(["event", *args])


# Prune


def merged_prs(pilot, *prs):
    pilot.result(
        "gh",
        "pr",
        "list",
        "--state",
        "merged",
        out=json.dumps([{"headRefName": n, "headRefOid": o} for n, o in prs]),
    )


def local_branches(pilot, *branches):
    pilot.result("git", "for-each-ref", out="\n".join(f"{n} {o}" for n, o in branches))


def deleted(pilot):
    return [call[3:] for call in pilot.calls if call[:3] == ("git", "branch", "-D")]


def test_prune_lists_only_branches_with_a_merged_pr(pilot):
    pilot.state = {"waiting_for": "new_issue"}
    merged_prs(pilot, ("issue-1-a", "1" * 40), ("issue-2-b", "2" * 40))
    local_branches(
        pilot,
        ("issue-1-a", "1" * 40),
        ("issue-2-b", "9" * 40),
        ("issue-3-c", "3" * 40),
    )

    message(pilot, "prune")

    assert pilot.sent == [("Löschen? issue-1-a", ("prune ja", "status"))]
    assert pilot.state["prune"] == ["issue-1-a"]
    assert deleted(pilot) == []


def test_prune_ja_deletes_the_listed_branches_still_merged(pilot):
    pilot.state = {"waiting_for": "new_issue", "prune": ["issue-1-a", "issue-2-b"]}
    local_branches(
        pilot,
        ("issue-1-a", "1" * 40),
        ("issue-2-b", "8" * 40),
        ("issue-4-d", "4" * 40),
    )
    merged_prs(
        pilot,
        ("issue-1-a", "1" * 40),
        ("issue-2-b", "2" * 40),
        ("issue-4-d", "4" * 40),
    )

    message(pilot, "prune ja")

    assert deleted(pilot) == [("issue-1-a",)]
    assert pilot.texts() == ["Gelöscht: issue-1-a"]
    assert pilot.state["prune"] == []


def test_prune_keeps_the_current_branch(pilot):
    pilot.state = {"waiting_for": "new_issue", "prune": ["issue-1-a"]}
    pilot.result("git", "branch", "--show-current", out="issue-1-a")
    merged_prs(pilot, ("issue-1-a", "1" * 40))
    local_branches(pilot, ("issue-1-a", "1" * 40))

    message(pilot, "prune ja")

    assert deleted(pilot) == []
    assert pilot.texts() == ["Nichts zu löschen, erst prune senden"]


def test_prune_ja_without_prune_deletes_nothing(pilot):
    pilot.state = {"waiting_for": "new_issue"}
    merged_prs(pilot, ("issue-1-a", "1" * 40))
    local_branches(pilot, ("issue-1-a", "1" * 40))

    message(pilot, "prune ja")

    assert deleted(pilot) == []


def test_prune_while_a_step_runs_is_refused(pilot):
    at_step(pilot, "issue")
    message(pilot, "prune")
    assert not pilot.ran("gh", "pr", "list", "--state", "merged")
