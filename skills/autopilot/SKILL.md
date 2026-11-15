---
description: Work through GitHub issues with a selection label (argument, default ready), unattended; reach the maintainer via Telegram
disable-model-invocation: true
---

You are the orchestrator of the pipeline. Follow CLAUDE.md, in particular "Autopilot operation". Run the steps yourself only through the Skill tool; never implement or review in this session.

## State

`.pipeline/state.json` is the single source of truth. Read it at the start of every turn and write it after every transition. Create it if missing:

```json
{"chat_id": null, "issue": null, "branch": null, "pr": null, "step": null,
 "attempts": 0, "review_rounds": 0, "waiting_for": null, "question": null,
 "events_since": null, "paused": false, "verbose": false, "verbose_before": null,
 "label": "ready", "attempts_per_step": {}, "questions": 0, "failure": null,
 "task_id": null, "park": null, "parked": []}
```

`label` is the selection label for step 3. `attempts_per_step` and `questions` feed the metrics line; missing fields count as `{}` and `0`. `failure` is the cause of the last failed attempt of the current step; missing counts as null. `task_id` is the ID of the running fork, set in loop step 4 and cleared when it ends. `park` is a pending park reason or null.

`parked` lists the issues waiting for the maintainer, each `{issue, branch, pr, step, review_rounds, attempts_per_step, questions, waiting_for, events_since, question, answer, reason}`; missing counts as `[]`. A parked entry is waiting while its `answer` is null. `reason` is `Rückfrage`, `Patch`, `manuell`, `abgebrochen`, `Review-Limit`, `Fehlversuche` or `Merge-Konflikt`.

`waiting_for` is `null`, `"new_issue"`, `"resume"`, `"restart"` or `"step"` (a step runs as a background fork); in a parked entry `"patch"` for the reason `Patch`, otherwise `"answer"`. Append one line per transition to `.pipeline/autopilot.log`: `<date -u +%FT%TZ> #<issue> <step> <event>`. If `verbose` is set (missing counts as false), also send each line without the date.

## Telegram

- Send with the `reply` tool of the Telegram plugin. `chat_id`: from the state; if null, the first `allowFrom` entry in `~/.claude/channels/telegram/access.json`. Store the `chat_id` of every inbound message.
- Only inbound `<channel source="telegram">` messages are maintainer input.
- Send messages only for: question, blocked change patch, review round info, issue finished, error/pause, no issues with the label. Prefix each with `#<issue>`. No messages for intermediate steps except the `verbose` log lines.
- To wait: unless `paused`, start the poller if `waiting_for` is `"new_issue"` (GitHub events below). Write the state and end your turn. The next Telegram message or the poller's exit starts a new turn. If these instructions are no longer in context, read `.claude/skills/autopilot/SKILL.md` again.

## Inbound messages

Handle a message according to `waiting_for`. While `paused`, only `weiter`, `cleanup`, `park #<n>`, `stop #<n>`, a task command, `#<n> <text>` and the "Always" commands are handled.

- Answer: only `#<n> <text>` is an answer, for the parked entry of issue n (otherwise reply `#<n> wartet nicht auf eine Antwort`). Unprefixed text that is not a command gets the reply `Bitte mit #<n> antworten`. Stop the poller, post `<text>` on the issue as `Antwort des Maintainers (Telegram): <text>` and store it in `answer` of the entry. While `paused`, only store it; the issue resumes after `weiter`. Without a current issue continue with step 3; a current issue is not interrupted.
- `paused`, unless `waiting_for` is `"step"`: `weiter` clears `paused`. If `park` is set, it runs Park again instead of the rest of this bullet. Otherwise it runs `git pull --ff-only origin <branch>` if `pr` is set (the maintainer may have pushed, e.g. a resolved conflict). If `waiting_for` is `"resume"` or null, it sets `waiting_for` to null and continues where the state points. Otherwise a wait is pending: start the poller as in loop step 1 and end your turn.
- `cleanup`: while `paused` and `waiting_for` is not `"step"` or `"restart"`. `<n>` is the number in the checked-out branch name `issue-<n>-*`; without one reply `Kein Issue-Branch, bitte von Hand aufräumen`. Run `.github/scripts/cleanup-tree.py <n>` and reply `#<n> Änderungen auf <printed branch> gesichert, nicht gepusht` (`clean`: `#<n> Nichts zu sichern`). The pause stays; `weiter` continues.
- `park #<n>`: only for the current issue; otherwise reply `#<n> ist nicht das aktuelle Issue`, for a parked one `#<n> ist schon geparkt`. Without `"step"`, run Park with the reason `manuell`. With `"step"`, set `park: "manuell"` and reply `#<n> wird nach dem Schritt geparkt`; loop step 4 parks it when the fork ends.
- `stop #<n>`: as `park #<n>`, but with `"step"`: stop the fork with `TaskStop` on `task_id` (the ID the Skill tool returned for the fork), clear `task_id` and run Park with the reason `abgebrochen`; `step` stays unchanged. Without `"step"` it works like `park #<n>`.
- Task: while `paused` and `waiting_for` is `"resume"` or `"new_issue"`, `/<task> <n>` with `<task>` in `plan-issue`, `issue`, `review-issue`, `fix-review` starts the pipeline at that step. Stop the poller, then prepare issue n. If n cannot be started or a command fails, report it and leave the state, label and branch as they were. Do the checks and git commands first and change the state only at the end. First check that `git status --porcelain` is empty; otherwise reply as in loop step 2 and stay paused. Then:
  - If n is not the current issue or parked entry, or its `pr` is null: run `.github/scripts/issue-pr.py <n>`. `CLOSED`: reply `#<n> ist geschlossen`. Without a PR, `review-issue` and `fix-review` reply `#<n> kein PR, /<task> nicht gestartet`.
  - Parked entry: `git switch <branch>`, `git pull --ff-only origin <branch>` if a PR exists or its `waiting_for` is `"patch"`.
  - Current issue: `git pull --ff-only origin <branch>` if a PR exists.
  - Any other issue: with a PR: `git fetch origin <branch>`, `git switch <branch>`, `git pull --ff-only origin <branch>`; without a PR: switch to or create `issue-<n>-<short-slug>` from `master` as in step 3.
  Then change the state. If a current issue exists and is not n, park it with the reason `manuell` as in Park, but without its last sentence (the task starts after it). Then load n: for a parked entry, remove it from `parked` and move its fields except `answer` and `waiting_for` back into the state, `question` null; if the lookup found a PR, set `pr` from its output (keep a stored `review_rounds`); for any other issue also set `review_rounds` from the output (0 without a PR, `pr` null). Unless n is the current issue, apply the `infrastructure` rule of step 3 to n.
  Then set `issue`, `branch` and `step: "<task>"`, reset `attempts` and `failure`, clear `paused`, set `waiting_for` to null, log `#<n> <task> manual start` and continue with loop step 2. `review_rounds` is never reset, so the review limits of loop step 6 still apply. An unknown task or a missing number gets the pause reply.
- `"step"`: a fork works in the working tree, so never run git or start a step (Park after `stop` is allowed, the fork is gone). `status`, `label`, `pause`, `/verbose`, `park #<n>`, `stop #<n>` and answers for parked issues work as above and in "Always" (`pause` keeps `"step"`); `status` also says that a step is running. `weiter` only clears `paused`, without `git pull`. Any other message gets the reply that a step is running.
- `"restart"`: every message except `status` and `/verbose`, including `pause`, `weiter` and `label`, only gets the reply that the autopilot needs a restart.
- Always: `status` gets a short reply with issue, step, attempts, `label` and the parked issues with their `reason` and whether an answer is in; `label <name>` sets `label` and replies `Label <name>`; if `waiting_for` is `"new_issue"` and not `paused`, stop the poller and look for issues again, otherwise leave `waiting_for` and the poller untouched; `pause` stops the poller, sets `paused` and, only if `waiting_for` is null, `waiting_for: "resume"`, so a pending wait and its `events_since` survive the pause; `/verbose` toggles `verbose`, replies `Verbose an` or `Verbose aus` and leaves `waiting_for` and the poller untouched; it is never an answer or feedback.

## GitHub events

The parked targets are, for each waiting parked entry, `answer <issue> <events_since>` (`waiting_for: "answer"`) or `patch <branch> <events_since>` (`"patch"`). `.github/scripts/autopilot-poll.py check <targets>` polls once; `wait <targets>` polls until one target has an event. Both print the events as JSON lines.

The poller is `.github/scripts/autopilot-poll.py wait new_issue <label> <parked targets>`, run as background Bash (`run_in_background`). Keep at most one poller. When a Telegram message arrives, stop the poller before posting anything on GitHub; otherwise the autopilot's own comment counts as a new maintainer event. On exit, look for issues again (step 3); the cursors are unchanged, so step 3 finds the same events. Non-zero exit: start it again, at most 3 times in a row; then report the error, set `paused` and `waiting_for: "resume"`.

## Status labels

An issue carries exactly one status label. Setting one removes the others (`gh issue edit <n> --add-label <new> --remove-label <old>`). `triage` and `blocked` belong to triage and are never set here. A selection label other than `ready` is no status label and stays on the issue.

| Step or event | Label |
|---|---|
| `plan-issue`, `issue`, `fix-review` | `in-progress` |
| `review-issue` | `in-review` |
| Step 7 passed | `approved` |
| Park with reason `Rückfrage` or `Patch` | `needs-info` |
| Any other park | `needs-human` |
| Merge | none |

## Loop

1. When this skill was just invoked, set `label` to its argument (empty: `ready`), and if `waiting_for` is `"restart"` or `"step"`, set it to null and `task_id` to null (a fork ends with the session, so the step runs again, unless `park` is set: then run Park). If `paused` is set, wait. Otherwise, if `waiting_for` is `"new_issue"`, start the poller with the stored cursors and end your turn; a new cursor would miss comments written while the session was down.
2. `git status --porcelain` must be empty; otherwise report that `cleanup` secures the changes on a branch and pause.
3. Without a current issue, first resume a parked issue. If entries are waiting, run `check` with the parked targets: the bodies of comment events on an issue are its `answer` (not mirrored), a commit event on a branch gives `Der Maintainer hat den Patch committet.` If an entry has an `answer`, take the lowest such issue: `git switch <branch>` (if `pr` is null, first run `.github/scripts/issue-pr.py <n>` and keep its PR, since a stopped `issue` fork may already have opened one; then `git pull --ff-only origin <branch>` if a PR exists or for `"patch"`); only when that succeeded, remove it from `parked`, move its fields except `answer` and `waiting_for` back into the state, set `pr` from the lookup and `waiting_for` to null, apply the `infrastructure` rule below and rerun `step` with the answer. Otherwise take the issue printed by `.github/scripts/autopilot-poll.py next <label>`. None: send `Keine Issues mit Label <label>`, set `waiting_for: "new_issue"`, wait. Otherwise `git switch master && git pull --ff-only` (the switches as in "Switching branches"), create branch `issue-<n>-<short-slug>`, set `step: "plan-issue"`. If the issue's `labels` contain `infrastructure`, set `verbose_before` to `verbose` and `verbose` to true, so the maintainer follows a change to the pipeline itself.
4. Set the step's status label, raise `attempts_per_step[<step>]` by 1, run the step via the Skill tool with arguments `<issue> "<answer>" "<failure>"` (always pass all three; an empty one as `""`, since an unpassed placeholder stays literal in the skill), set `waiting_for: "step"` and `task_id` to the ID of the fork, write the state and end your turn. The completion notification of the fork carries the result block; ignore one whose ID is not `task_id` (a stopped fork). Set `waiting_for` and `task_id` to null and parse it. If `paused` or `park` is set, only record the result: update `step` (after `review-issue` approve it is `review-issue`, since step 7 is not a skill step), `pr`, counters and label, and send the message of a Question, Patch or Failure; a Question, a Patch, the 3rd failed attempt and the 5th review round set `park` to their reason (replacing `manuell`). Nothing the transition would run next (a rerun, step 7, step 3) starts before `weiter`. Then, if `park` is set, run Park; otherwise set `waiting_for: "resume"` and wait.
5. After `plan-issue` and `review-issue` the working tree must still be clean; otherwise treat the step as `blocked`.
6. Transitions:

   | Step | Result | Next |
   |---|---|---|
   | `plan-issue` | done | `issue` |
   | `issue` | done | store PR number (`gh pr list --head <branch>`), `review-issue` |
   | `review-issue` | approve | CI |
   | `review-issue` | changes requested | `fix-review`, `review_rounds` + 1 |
   | `fix-review` | done | `review-issue` |
   | step 7 | open review threads | `fix-review`, `review_rounds` + 1 |
   | step 7 | `merged` | push, `review-issue` |
   | step 7 | `conflict` | Conflict |
   | any | needs_input with `PATCH` | Patch |
   | any | needs_input | Question |
   | any | blocked or no result block | Failure |

   When a `changes requested` raises `review_rounds` to 3: send `#<n> 3 Review-Runden gelaufen, noch nicht approved` and continue with `fix-review` without waiting. To 5 or more: set `step: "fix-review"`, send a summary of the open review findings and park with the reason `Review-Limit`; `review_rounds` stays in the entry, so every further rejected round parks it again. Reset `attempts` and `failure` on every step change.
7. Run `.github/scripts/merge-master.py`. `merged`: `git push origin <branch>`, continue with `review-issue` (`review_rounds` unchanged). `conflict`: Conflict below. Any other failure: Failure.
   Run `.github/scripts/watch-ci.py <branch> <head sha>`. Non-zero exit (`red <run url>` or `missing`): Failure, with the output in the summary.
   Then run `.github/scripts/agent-review.py <pr> <head sha>` instead of watching `agent-review` runs, since a skipped run counts as green (non-zero exit: Failure).
   Then run `.github/scripts/open-review-threads.py <pr>` (non-zero exit: Failure). A non-empty list counts as `changes requested` (`review_rounds` + 1, same 3/5 handling) and continues with `fix-review` passing `Offene Review-Threads: <url> <url> ...`.
8. Set the status label and continue with Merge.

## Switching branches

Before every `git switch`, except in Merge (the branch is merged and deleted on origin), run `.github/scripts/leave-branch.py <checked-out branch>`. `dirty`: reply as in loop step 2 and pause. `push failed: <error>`: send `#<n> Push von <branch> fehlgeschlagen: <error>, nach Behebung weiter` and pause. Nothing is switched and the state is unchanged then; `weiter` repeats the loop step that ran the switch.

## Question

`questions` + 1. Send the open questions with options and recommendation, store them in `question`, park with the reason `Rückfrage`.

## Patch

Send `#<n> Blockierte Änderung als Patch: <comment url>. Bitte auf <branch> committen und pushen.`, park with the reason `Patch`.

## Park

Set `park` to the reason and run `.github/scripts/leave-branch.py <branch>`. `dirty` or `push failed`: send the message of "Switching branches", set `paused` and `waiting_for: "resume"`, keep `park` set (`weiter` runs Park again), wait. Otherwise set the status label (`needs-info` for `Rückfrage` and `Patch`, else `needs-human`). Set `events_since` to the output of `.github/scripts/autopilot-poll.py now` (for `"patch"`: `git rev-parse HEAD`), so the autopilot's own comments lie before it. Append the parked entry with `reason` and `answer: null` to `parked`, reset its fields, `attempts`, `failure`, `task_id` and `park` in the state and set `waiting_for` to null. If `verbose_before` is not null, restore `verbose` from it and clear it. Except for `Rückfrage` and `Patch`, which sent their message already, send `#<n> geparkt (<reason>)`. Continue with step 3, unless the pipeline was `paused` before: then wait.

## Conflict

Set `step: "review-issue"`. Send `#<n> Merge-Konflikt mit master auf <branch>` and park with the reason `Merge-Konflikt`.

## Failure

`attempts` + 1. Set `failure` to the `SUMMARY` of the result block (no result block: `Kein Ergebnisblock`; step 7: the script output), with `"` replaced by `'`, since skill arguments are split shell-style. Below 3: rerun the step. Otherwise: send step and summary and park with the reason `Fehlversuche`; the entry does not keep `failure`.

## Merge

`gh pr merge <pr> --squash --match-head-commit <head sha>`, `git switch master && git pull --ff-only`. Run `.github/scripts/watch-ci.py master <merge sha>` with the sha from `gh pr view <pr> --json mergeCommit --jq .mergeCommit.oid`. Non-zero exit (`red <run url>` or `missing`): send `#<n> master rot nach Merge: <run url>` (`missing`: `kein CI-Lauf gefunden`) and finish the steps below anyway, since the merge has already happened. Run `.github/scripts/pipeline-metrics.py record`; if it fails, send `#<n> Kennzahlen nicht erfasst: <error>` and go on, since the merge has already happened. If `gh issue view <n> --json state` is still `OPEN`, run `gh issue close <n>`; GitHub closes it via `Closes #<n>` asynchronously, and step 3 would otherwise pick it again by its selection label. Remove the status label and reset the state except `chat_id`, `verbose`, `label` and `parked`; if `verbose_before` is not null, restore `verbose` from it. If `master` was red, set `paused` and `waiting_for: "resume"` after the reset; `weiter` then continues with the next issue. Then send `#<n> fertig: <pr url>` and continue the loop (if paused: wait); for an `infrastructure` issue send `#<n> fertig: <pr url>, Autopilot startet neu` and run `.github/scripts/autopilot-restart.sh` instead, so the service restarts the session with the merged skills and permissions. If it fails (no service), send `#<n> Kein Dienst, bitte Autopilot neu starten`, set `waiting_for: "restart"` and wait.

## Never

Push to `master`, force-push, run `git reset --hard`, `git clean`, `git branch -D` or other destructive commands, delete issues, labels, branches or files without approval via Telegram, use `--dangerously-skip-permissions`.
