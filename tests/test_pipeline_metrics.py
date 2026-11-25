import json
import subprocess

import pytest
from conftest import load_script

MERGED_AT = "2026-11-13T12:00:00Z"
STATE = {
    "issue": 69,
    "pr": 98,
    "review_rounds": 2,
    "attempts_per_step": {"plan-issue": 1, "issue": 3},
    "questions": 1,
    "label": "ready",
}


@pytest.fixture
def metrics():
    return load_script("pipeline-metrics.py")


def label_event(name, created_at, event="labeled"):
    return {"event": event, "label": {"name": name}, "created_at": created_at}


def fake_github(monkeypatch, metrics, events):
    monkeypatch.setattr(
        metrics, "gh_api", lambda path: json.dumps({"merged_at": MERGED_AT})
    )
    monkeypatch.setattr(metrics, "gh", lambda path: events)


def record(tmp_path, metrics, state):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state))
    log_path = tmp_path / "autopilot.log"
    log_path.write_text("2026-11-13T10:00:00Z #69 plan-issue start\n")
    metrics.record(state_path, log_path)
    return log_path


def test_record_appends_metrics_since_last_selection_label(
    monkeypatch, tmp_path, metrics
):
    fake_github(
        monkeypatch,
        metrics,
        [
            label_event("ready", "2026-11-13T08:00:00Z"),
            label_event("ready", "2026-11-13T10:00:00Z"),
            label_event("ready", "2026-11-13T11:00:00Z", event="unlabeled"),
            label_event("in-progress", "2026-11-13T11:30:00Z"),
        ],
    )

    log_path = record(tmp_path, metrics, STATE)

    assert log_path.read_text().splitlines()[1] == (
        f"{MERGED_AT} #69 merge metrics "
        '{"issue": 69, "pr": 98, "review_rounds": 2, '
        '"attempts": {"plan-issue": 1, "issue": 3}, '
        '"questions": 1, "duration_s": 7200, "usage": {}}'
    )


def test_record_defaults_missing_state_fields(monkeypatch, tmp_path, metrics):
    fake_github(monkeypatch, metrics, [label_event("ready", "2026-11-13T11:00:00Z")])
    old_state = {"issue": 69, "pr": 98, "review_rounds": 0}

    log_path = record(tmp_path, metrics, old_state)

    recorded = metrics.read_metrics(log_path)[0][0]
    assert recorded["attempts"] == {}
    assert recorded["questions"] == 0
    assert recorded["duration_s"] == 3600


def test_record_without_label_event_has_no_duration(monkeypatch, tmp_path, metrics):
    fake_github(monkeypatch, metrics, [label_event("bug", "2026-11-13T11:00:00Z")])

    log_path = record(tmp_path, metrics, STATE)

    assert metrics.read_metrics(log_path)[0][0]["duration_s"] is None


def log_line(issue, rounds, attempts, questions, duration):
    data = {
        "issue": issue,
        "pr": issue + 1,
        "review_rounds": rounds,
        "attempts": attempts,
        "questions": questions,
        "duration_s": duration,
    }
    return f"{MERGED_AT} #{issue} merge metrics {json.dumps(data)}"


def test_summary_aggregates_metrics_lines_only(tmp_path, metrics):
    log_path = tmp_path / "autopilot.log"
    log_path.write_text(
        "\n".join(
            [
                "2026-11-13T10:00:00Z #1 plan-issue start",
                log_line(1, 1, {"plan-issue": 1, "issue": 2}, 0, 3600),
                "2026-11-13T11:00:00Z #2 merge done",
                log_line(2, 4, {"plan-issue": 1, "issue": 3}, 2, 10800),
                log_line(3, 1, {"plan-issue": 2}, 1, None),
            ]
        )
        + "\n"
    )

    assert metrics.summarize(*metrics.read_metrics(log_path)).splitlines() == [
        "3 Issues",
        "Review-Runden: Mittel 2.0, Max 4",
        "Versuche issue: Mittel 2.5",
        "Versuche plan-issue: Mittel 1.3",
        "Rückfragen: 3",
        "Dauer: Median 2.0 h, Max 3.0 h",
    ]


@pytest.mark.parametrize("content", [None, "", "2026-11-13T10:00:00Z #1 start\n"])
def test_summary_without_metrics_lines(tmp_path, metrics, content):
    log_path = tmp_path / "autopilot.log"
    if content is not None:
        log_path.write_text(content)

    assert metrics.summarize(*metrics.read_metrics(log_path)) == "0 Issues"


@pytest.mark.parametrize("argv", [[], ["record", "extra"], ["unknown"]])
def test_wrong_arguments_exit_with_usage(metrics, argv):
    with pytest.raises(SystemExit) as exit:
        metrics.main(argv)

    assert exit.value.code == metrics.__doc__


def test_summary_reads_log_of_project_in_working_directory(
    tmp_path, monkeypatch, metrics, capsys
):
    (tmp_path / ".pipeline").mkdir()
    (tmp_path / ".pipeline" / "autopilot.log").write_text(
        log_line(1, 1, {"issue": 1}, 0, 3600) + "\n"
    )
    monkeypatch.chdir(tmp_path)

    metrics.main(["summary"])

    assert capsys.readouterr().out.startswith("1 Issues\n")


def test_summary_reads_log_of_project_root_from_subdirectory(
    tmp_path, monkeypatch, metrics, capsys
):
    (tmp_path / ".pipeline").mkdir()
    (tmp_path / ".pipeline" / "autopilot.log").write_text(
        log_line(1, 1, {"issue": 1}, 0, 3600) + "\n"
    )
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "docs").mkdir()
    monkeypatch.chdir(tmp_path / "docs")

    metrics.main(["summary"])

    assert capsys.readouterr().out.startswith("1 Issues\n")


def test_park_records_reason_and_usage(tmp_path, metrics):
    state = {
        **STATE,
        "usage": {"issue": {"forks": 2, "tokens": 900, "duration_s": 60}},
    }
    (tmp_path / "state.json").write_text(json.dumps(state))
    log_path = tmp_path / "autopilot.log"

    metrics.park(tmp_path / "state.json", log_path, "Failure")

    merged, parked = metrics.read_metrics(log_path)
    assert merged == []
    assert parked == [
        {
            "issue": 69,
            "reason": "Failure",
            "review_rounds": 2,
            "attempts": {"plan-issue": 1, "issue": 3},
            "questions": 1,
            "usage": state["usage"],
        }
    ]


def test_summary_shows_parked_issues_and_tokens_per_step(metrics):
    usage = {"issue": {"forks": 1, "tokens": 1000, "duration_s": 60}}
    merged = [
        {
            "review_rounds": 1,
            "attempts": {},
            "questions": 0,
            "duration_s": None,
            "usage": usage,
        }
    ]
    parked = [
        {"reason": "Failure", "usage": {"issue": {"tokens": 3000}}},
        {"reason": "Failure", "usage": {}},
        {"reason": "Rückfrage", "usage": {}},
    ]

    lines = metrics.summarize(merged, parked).splitlines()

    assert "Geparkt: 3 (Failure 2, Rückfrage 1)" in lines
    assert lines[-1] == "Tokens issue: Mittel 2000 je Issue"


@pytest.mark.parametrize("argv", [["park"], ["park", "a", "b"]])
def test_park_needs_one_reason(metrics, argv):
    with pytest.raises(SystemExit):
        metrics.main(argv)
