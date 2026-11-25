---
description: Work through GitHub issues with a selection label (argument, default ready), unattended; reach the maintainer via Telegram
disable-model-invocation: true
---

You are the orchestrator of the pipeline. Follow the pipeline rules in `${CLAUDE_PLUGIN_ROOT}/rules/workflow.md`, in particular "Autopilot operation", and the project rules. Run the steps yourself only through the Skill tool, as skills of this plugin with the prefix `pipeline:` (`pipeline:plan-issue`, `pipeline:find-answer`, ...); never implement or review in this session. The scripts named below are commands of this plugin; run them without a path. `<default>` is the default branch of the project, printed by `default-branch.py`.

## State

`.pipeline/state.json` is the single source of truth. Read it at the start of every turn and write it after every transition. Create it if missing:

```json
{"chat_id": null, "issue": null, "branch": null, "pr": null, "step": null,
 "attempts": 0, "review_rounds": 0, "waiting_for": null, "question": null,
 "events_since": null, "paused": false, "verbose": false, "verbose_before": null,
 "label": "ready", "attempts_per_step": {}, "questions": 0, "failure": null,
 "task_id": null, "park": null, "parked": []}
```

`label` is the selection label for step 3. In the step `setprio` (an issue without status label is checked, loop step 3) `branch` and `pr` are null. `attempts_per_step` and `questions` feed the metrics line; missing fields count as `{}` and `0`. `failure` is the cause of the last failed attempt of the current step; missing counts as null. `task_id` is the ID of the running fork, set in loop step 4 and cleared when it ends. `park` is a pending park reason or null.

`parked` lists the issues waiting for the maintainer, each `{issue, branch, pr, step, review_rounds, attempts_per_step, questions, waiting_for, events_since, question, answer, reason}`; missing counts as `[]`. A parked entry is waiting while its `answer` is null. `reason` is `Rückfrage`, `Patch`, `manuell`, `abgebrochen`, `Review-Limit`, `Fehlversuche` or `Merge-Konflikt`.

`waiting_for` is `null`, `"new_issue"`, `"resume"`, `"restart"` or `"step"` (a step runs as a background fork); in a parked entry `"patch"` for the reason `Patch`, otherwise `"answer"`. Append one line per transition to `.pipeline/autopilot.log`: `<date -u +%FT%TZ> #<issue> <step> <event>`. If `verbose` is set (missing counts as false), also send each line without the date.

## Telegram

- Send with the `reply` tool of the Telegram plugin. `chat_id`: from the state; if null, the first `allowFrom` entry in `~/.claude/channels/telegram/access.json`. Store the `chat_id` of every inbound message.
- Wherever this skill sends a message listed in the button table below, it goes through `telegram-send.py <button>...` instead: the text on stdin as a heredoc with a quoted delimiter, the buttons as arguments. If it fails (e.g. text over 4096 characters), send the same text without buttons with `reply`, so no message is lost. A button is a reply keyboard key: pressing it sends its label as a message, so every label is a valid command or answer.
- Only inbound `<channel source="telegram">` messages are maintainer input.
- Send messages only for: question, blocked change patch, review round info, issue finished, new followup issue, pipeline finding, error/pause, no issues with the label. Prefix each with `#<issue>`. No messages for intermediate steps except the `verbose` log lines.

  | Message | Buttons |
  |---|---|
  | Question (one question) | `#<n> a`, `#<n> b`, ... one per option |
  | Question (several questions) | `#<n> Empfehlungen` |
  | Parked (`#<n> geparkt (<reason>)`) | `#<n> weiter`, `status` |
  | Patch | `status` |
  | `<default>` red after Merge | `weiter`, `status` |
  | A step is running (reply to `status`, reply to any other message) | `park #<n>`, `stop #<n>` |
  | Dirty working tree (loop step 2, "Switching branches", Park, Task) | `cleanup`, `status` |

- To wait: unless `paused`, start the poller if `waiting_for` is `"new_issue"` (GitHub events below). Write the state and end your turn. The next Telegram message or the poller's exit starts a new turn. If these instructions are no longer in context, read `${CLAUDE_SKILL_DIR}/SKILL.md` again.

## Inbound messages

Handle a message according to `waiting_for`. While `paused`, only `weiter`, `cleanup`, `park #<n>`, `stop #<n>`, a task command, `update`, `#<n> <text>` and the "Always" commands are handled.

- Answer: only `#<n> <text>` is an answer, for the parked entry of issue n (otherwise reply `#<n> wartet nicht auf eine Antwort`); the current issue accepts it only while `question` is set: stop the fork with `TaskStop`, post the answer as below, clear `question` and `task_id`, and rerun `step` with `<text>` as the answer, or with `park` or `paused` set park as for the search result. An answer that is only an option letter (`#<n> a`) or `Empfehlungen` is expanded with the stored `question` before it is posted and passed on: `a) <option text>` or `Empfehlungen übernehmen: 1. <recommendation> 2. ...`, since `fix-review` reads only PR comments and a bare `a` has no context there; for a parked entry the stored `question` of the entry counts. Unprefixed text that is not a command gets the reply `Bitte mit #<n> antworten`. Stop the poller, post `<text>` on the issue as `Antwort des Maintainers (Telegram): <text>` and store it in `answer` of the entry. While `paused`, only store it; the issue resumes after `weiter`. Without a current issue continue with step 3; a current issue is not interrupted.
- `paused`, unless `waiting_for` is `"step"`: `weiter` clears `paused`. If `park` is set, it runs Park again instead of the rest of this bullet. Otherwise it runs `git pull --ff-only origin <branch>` if `pr` is set (the maintainer may have pushed, e.g. a resolved conflict). If `waiting_for` is `"resume"` or null, it sets `waiting_for` to null and continues where the state points. Otherwise a wait is pending: start the poller as in loop step 1 and end your turn.
- `cleanup`: while `paused` and `waiting_for` is not `"step"` or `"restart"`. `<n>` is the number in the checked-out branch name `issue-<n>-*`; without one reply `Kein Issue-Branch, bitte von Hand aufräumen`. Run `cleanup-tree.py <n>` and reply `#<n> Änderungen auf <printed branch> gesichert, nicht gepusht` (`clean`: `#<n> Nichts zu sichern`). The pause stays; `weiter` continues.
- `park #<n>`: only for the current issue; otherwise reply `#<n> ist nicht das aktuelle Issue`, for a parked one `#<n> ist schon geparkt`. Without `"step"`, run Park with the reason `manuell`. With `"step"`, set `park: "manuell"` and reply `#<n> wird nach dem Schritt geparkt`; loop step 4 parks it when the fork ends.
- `stop #<n>`: as `park #<n>`, but with `"step"`: stop the fork with `TaskStop` on `task_id` (the ID the Skill tool returned for the fork), clear `task_id` and run Park with the reason `abgebrochen`; `step` stays unchanged. Without `"step"` it works like `park #<n>`.
- Task: while `paused` and `waiting_for` is `"resume"` or `"new_issue"`, `/<task> <n>` with `<task>` in `plan-issue`, `issue`, `review-issue`, `fix-review` starts the pipeline at that step. Stop the poller, then prepare issue n. If n cannot be started or a command fails, report it and leave the state, label and branch as they were. Do the checks and git commands first and change the state only at the end. First check that `git status --porcelain` is empty; otherwise reply as in loop step 2 and stay paused. Then:
  - If n is not the current issue or parked entry, or its `pr` is null: run `issue-pr.py <n>`. `CLOSED`: reply `#<n> ist geschlossen`. Without a PR, `review-issue` and `fix-review` reply `#<n> kein PR, /<task> nicht gestartet`.
  - Parked or current entry whose `branch` is null (step `setprio`): treat it as "any other issue" below.
  - Parked entry: `git switch <branch>`, `git pull --ff-only origin <branch>` if a PR exists or its `waiting_for` is `"patch"`.
  - Current issue: `git pull --ff-only origin <branch>` if a PR exists.
  - Any other issue: with a PR: `git fetch origin <branch>`, `git switch <branch>`, `git pull --ff-only origin <branch>`; without a PR: switch to or create `issue-<n>-<short-slug>` from `<default>` as in step 3.
  Then change the state. If a current issue exists and is not n, park it with the reason `manuell` as in Park, but without its last sentence (the task starts after it). Then load n: for a parked entry, remove it from `parked` and move its fields except `answer` and `waiting_for` back into the state, `question` null (for the current issue also clear `question`); if the lookup found a PR, set `pr` from its output (keep a stored `review_rounds`); for any other issue also set `review_rounds` from the output (0 without a PR, `pr` null). Unless n is the current issue, apply the `infrastructure` rule of step 3 to n.
  Then set `issue`, `branch` and `step: "<task>"`, reset `attempts` and `failure`, clear `paused`, set `waiting_for` to null, log `#<n> <task> manual start` and continue with loop step 2. `review_rounds` is never reset, so the review limits of loop step 6 still apply. An unknown task or a missing number gets the pause reply.
- `update`: only while `issue` is null and `waiting_for` is `"new_issue"` or `"resume"`; otherwise reply `update nur ohne aktuelles Issue`. Stop the poller. If `git status --porcelain` is not empty, reply as in loop step 2. Otherwise run `release-changed.sh`: if it prints a release, a merged pull request moved the pin, so run `git switch <default> && git pull --ff-only` (the switches as in "Switching branches") and Restart with `Autopilot startet neu auf <release>`. If it prints nothing, run `.claude/skills/pipeline/host/update-pipeline.sh` and reply its last line (the URL of the bump pull request, or that the pin is up to date). On a non-zero exit reply its error. Without a restart, keep `waiting_for` and `paused` and start the poller again if `waiting_for` is `"new_issue"` and not `paused`.
- `"step"`: a fork works in the working tree, so never run git or start a step (Park after `stop`, or Park or the rerun after `TaskStop` of `find-answer`, is allowed, the fork is gone). `status`, `label`, `help`, `pause`, `/verbose`, `park #<n>`, `stop #<n>`, answers for parked issues and the answer for the current issue while `question` is set work as above and in "Always" (`pause` keeps `"step"`); `status` also says that a step is running. `weiter` only clears `paused`, without `git pull`. Any other message gets the reply that a step is running.
- `"restart"`: every message except `status`, `help` and `/verbose`, including `pause`, `weiter` and `label`, only gets the reply that the autopilot needs a restart.
- Always: `help` replies with the section `## Telegram-Befehle` of `${CLAUDE_PLUGIN_ROOT}/docs/autopilot.md` as plain text (read the file; without the heading, Markdown and the intro sentence); `status` gets a short reply with issue, step, attempts, `label` and the parked issues with their `reason` and whether an answer is in; `label <name>` sets `label` and replies `Label <name>`; if `waiting_for` is `"new_issue"` and not `paused`, stop the poller and look for issues again, otherwise leave `waiting_for` and the poller untouched; `pause` stops the poller, sets `paused` and, only if `waiting_for` is null, `waiting_for: "resume"`, so a pending wait and its `events_since` survive the pause; `/verbose` toggles `verbose`, replies `Verbose an` or `Verbose aus` and leaves `waiting_for` and the poller untouched; it is never an answer or feedback.

## GitHub events

The parked targets are, for each waiting parked entry, `answer <issue> <events_since>` (`waiting_for: "answer"`) or `patch <branch> <events_since>` (`"patch"`). `autopilot-poll.py check <targets>` polls once; `wait <targets>` polls until one target has an event. Both print the events as JSON lines.

The poller is `autopilot-poll.py wait new_issue <label> <parked targets>`, run as background Bash (`run_in_background`). Keep at most one poller. When a Telegram message arrives, stop the poller before posting anything on GitHub; otherwise the autopilot's own comment counts as a new maintainer event. On exit, look for issues again (step 3); the cursors are unchanged, so step 3 finds the same events. Non-zero exit: start it again, at most 3 times in a row; then report the error, set `paused` and `waiting_for: "resume"`.

## Status labels

An issue carries exactly one status label. Setting one removes the others (`gh issue edit <n> --add-label <new> --remove-label <old>`). A selection label other than `ready` is no status label and stays on the issue. The types `bug` and `enhancement` are no status labels either; `setprio` sets them.

| Step or event | Label |
|---|---|
| `plan-issue`, `issue`, `fix-review` | `in-progress` |
| `review-issue` | `in-review` |
| `setprio` running | none; `done`: `ready` |
| Step 7 passed | `approved` |
| Question, while `find-answer` runs | `question` |
| Park, any reason | `parked` |
| Merge | none |

## Loop

1. When this skill was just invoked, run `release-changed.sh record`, so a later merge of a new pin is detected, set `label` to its argument (empty: `ready`), and if `waiting_for` is `"restart"` or `"step"`, set it to null and `task_id` to null (a fork ends with the session, so the step runs again, unless `park` is set: then run Park; if `question` is set, start `find-answer` again as in Question, without `questions` + 1, without a new message and keeping `events_since`, instead of the step). If `paused` is set, wait. Otherwise, if `waiting_for` is `"new_issue"`, start the poller with the stored cursors and end your turn; a new cursor would miss comments written while the session was down.
2. `git status --porcelain` must be empty; otherwise report that `cleanup` secures the changes on a branch and pause.
3. Without a current issue, first run `release-changed.sh` (non-zero exit: send `Release-Prüfung fehlgeschlagen: <error>` and go on). If it prints a release, a merge moved the pin, also one the maintainer made: `git switch <default> && git pull --ff-only` (the switches as in "Switching branches") and Restart with `Autopilot startet neu auf <release>`, so no issue runs on the old release. Otherwise first resume a parked issue. If entries are waiting, run `check` with the parked targets: the bodies of comment events on an issue are its `answer` (not mirrored), a commit event on a branch gives `Der Maintainer hat den Patch committet.` If an entry has an `answer`, take the lowest such issue: if `branch` is null (step `setprio`), `git switch <default> && git pull --ff-only` (the switches as in "Switching branches"), else `git switch <branch>` (if `pr` is null, first run `issue-pr.py <n>` and keep its PR, since a stopped `issue` fork may already have opened one; then `git pull --ff-only origin <branch>` if a PR exists or for `"patch"`); only when that succeeded, remove it from `parked`, move its fields except `question`, `answer` and `waiting_for` back into the state, set `pr` from the lookup and `waiting_for` to null, apply the `infrastructure` rule below (not for `setprio`) and rerun `step` with the answer. Otherwise take the lowest issue printed by `autopilot-poll.py untriaged <label>`: set `issue`, `step: "setprio"`, `branch` and `pr` null, run `git switch <default> && git pull --ff-only` (the switches as in "Switching branches"), so the step judges against the rules on `<default>`, and continue with step 4. If it has the label `followup`, first send `#<n> Neues Folge-Issue: <title>. <one sentence from its body>`. Otherwise take the issue printed by `autopilot-poll.py next <label>`. None: send `Keine Issues mit Label <label>`, set `waiting_for: "new_issue"`, wait. Otherwise `git switch <default> && git pull --ff-only` (the switches as in "Switching branches"), create branch `issue-<n>-<short-slug>`, set `step: "plan-issue"`. If the issue's `labels` contain `infrastructure`, set `verbose_before` to `verbose` and `verbose` to true, so the maintainer follows a change to the pipeline itself.
4. Set the step's status label (none for `setprio`), raise `attempts_per_step[<step>]` by 1, run the step via the Skill tool with arguments `<issue> "<answer>" "<failure>"` (always pass all three; an empty one as `""`, since an unpassed placeholder stays literal in the skill; `"` inside `<answer>` and `<failure>` replaced by `'`, since skill arguments are split shell-style), set `waiting_for: "step"` and `task_id` to the ID of the fork, write the state and end your turn. The completion notification of the fork carries the result block; ignore one whose ID is not `task_id` (a stopped fork). Set `waiting_for` and `task_id` to null and parse it. If it has a `PIPELINE_FINDING: <comment url>` line, send `#<n> Pipeline-Befund: <comment url>` once; the transition is unchanged. If `question` is set, it is the result of `find-answer`: handle it as in Question and skip the rest of this step. If `paused` or `park` is set, only record the result: update `step` (after `review-issue` approve it is `review-issue`, since step 7 is not a skill step; after `setprio` done with `park` set it stays `setprio`, otherwise run Setprio done instead), `pr`, counters and label, and send the message of a Question, Patch or Failure; a Question, a Patch, the 3rd failed attempt and the 5th review round set `park` to their reason (replacing `manuell`). Nothing the transition would run next (a rerun, step 7, step 3) starts before `weiter`. Then, if `park` is set, run Park; otherwise set `waiting_for: "resume"` and wait.
5. After `plan-issue`, `review-issue` and `setprio` the working tree must still be clean; otherwise treat the step as `blocked`.
6. Transitions:

   | Step | Result | Next |
   |---|---|---|
   | `setprio` | done | Setprio done |
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
7. Run `merge-default-branch.py`. `merged`: `git push origin <branch>`, continue with `review-issue` (`review_rounds` unchanged). `conflict`: Conflict below. Any other failure: Failure.
   Run `watch-ci.py <branch> <head sha>`. Non-zero exit (`red <run url>` or `missing`): Failure, with the output in the summary.
   Then run `agent-review.py sync <pr> <head sha>`: it re-runs a run of the push that turned red before the review and prints `green` only when the latest review on the head commit is an approve and the required check `agent-review` is green (any other output or a non-zero exit: Failure, with the output in the summary).
   Then run `open-review-threads.py <pr>` (non-zero exit: Failure). A non-empty list counts as `changes requested` (`review_rounds` + 1, same 3/5 handling) and continues with `fix-review` passing `Offene Review-Threads: <url> <url> ...`.
8. Set the status label and continue with Merge.

## Switching branches

Before every `git switch`, except in Merge (the branch is merged and deleted on origin), run `leave-branch.py <checked-out branch>`. `dirty`: reply as in loop step 2 and pause. `push failed: <error>`: send `#<n> Push von <branch> fehlgeschlagen: <error>, nach Behebung weiter` and pause. Nothing is switched and the state is unchanged then; `weiter` repeats the loop step that ran the switch.

## Setprio done

Set the status label `ready` (removing `question` or `parked` if present). Reset the state except `chat_id`, `verbose`, `label`, `parked` and `paused`, send no message. If `paused`, set `waiting_for: "resume"` and wait; otherwise continue with loop step 3.

## Question

`questions` + 1. Store the open questions in `question`, set the status label `question` and send them with options and recommendation. If `paused` or `park` is set, park with the reason `Rückfrage` without a search. Otherwise set `events_since` to the output of `autopilot-poll.py now`, so a maintainer comment written during the search is not lost, and run `find-answer` via the Skill tool with `<issue> "<question>" ""` (`"` replaced by `'`), set `waiting_for: "step"` and `task_id`, write the state and end your turn. `step` stays the asking step, and the search does not count in `attempts_per_step`.

On the search result (loop step 4), clear `task_id`. First run `autopilot-poll.py check answer <issue> <events_since>`; the bodies of its comment events are the maintainer's answer and replace the result: clear `question`, rerun `step` with them as the answer (loop step 4), or with `park` or `paused` set park with `Rückfrage` and store them as `answer`. Otherwise:

- `done`: post `Antwort gefunden: <summary>` on the issue and send `#<n> Antwort gefunden: <summary>`, clear `question`. If `park` is set, park with its reason and `answer: null`, so the manual park holds. If only `paused` is set, park with `Rückfrage` and store the summary as `answer` of the entry, so loop step 3 resumes the issue after `weiter`. Otherwise rerun `step` with the summary as the answer (loop step 4).
- `needs_input`, `blocked` or no result block: park with the reason of `park`, else `Rückfrage`.

## Patch

Send `#<n> Blockierte Änderung als Patch: <comment url>. Bitte auf <branch> committen und pushen.`, park with the reason `Patch`.

## Park

Set `park` to the reason and run `leave-branch.py <branch>` (skipped if `branch` is null). `dirty` or `push failed`: send the message of "Switching branches", set `paused` and `waiting_for: "resume"`, keep `park` set (`weiter` runs Park again), wait. Otherwise set the status label `parked`. Set `events_since` to the output of `autopilot-poll.py now` (for `"patch"`: `git rev-parse HEAD`), so the autopilot's own comments lie before it. Append the parked entry with `reason` and `answer` (the found answer of Question, else null) to `parked`, reset its fields, `attempts`, `failure`, `task_id` and `park` in the state and set `waiting_for` to null. If `verbose_before` is not null, restore `verbose` from it and clear it. Except for `Rückfrage` and `Patch`, which sent their message already, send `#<n> geparkt (<reason>)`. Continue with step 3, unless the pipeline was `paused` before: then wait.

## Conflict

Set `step: "review-issue"`. Send `#<n> Merge-Konflikt mit <default> auf <branch>` and park with the reason `Merge-Konflikt`.

## Failure

`attempts` + 1. Set `failure` to the `SUMMARY` of the result block (no result block: `Kein Ergebnisblock`; step 7: the script output). Below 3: rerun the step. Otherwise: send step and summary and park with the reason `Fehlversuche`; the entry does not keep `failure`.

## Merge

`gh pr merge <pr> --squash --match-head-commit <head sha>`. Non-zero exit: Failure with its output, and nothing below runs; the step is still `review-issue`, whose fresh approve leads to step 7 again. Then `git switch <default> && git pull --ff-only`. Run `watch-ci.py <default> <merge sha>` with the sha from `gh pr view <pr> --json mergeCommit --jq .mergeCommit.oid`. Non-zero exit (`red <run url>` or `missing`): send `#<n> <default> rot nach Merge: <run url>` (`missing`: `kein CI-Lauf gefunden`) and finish the steps below anyway, since the merge has already happened. Run `pipeline-metrics.py record`; if it fails, send `#<n> Kennzahlen nicht erfasst: <error>` and go on, since the merge has already happened. If `gh issue view <n> --json state` is still `OPEN`, run `gh issue close <n>`; GitHub closes it via `Closes #<n>` asynchronously, and step 3 would otherwise pick it again by its selection label. Remove the status label and reset the state except `chat_id`, `verbose`, `label` and `parked`; if `verbose_before` is not null, restore `verbose` from it. If `<default>` was red, set `paused` and `waiting_for: "resume"` after the reset; `weiter` then continues with the next issue. Then send `#<n> fertig: <pr url>` and continue the loop (if paused: wait); loop step 3 restarts the autopilot if the merge moved the pin.

## Restart

The session loads skills, agents, hook and rules only at start, so a new pinned release needs a restart. In the pipeline repository itself (`.claude/pipeline-release` exists) first run `.claude/skills/pipeline/host/use-release.sh`, which moves the release worktree to the new pin; non-zero exit: send its error, set `paused` and `waiting_for: "resume"`, wait. Send the message, then run `autopilot-restart.sh`, so the service restarts the session on the new release. If it fails (no service), send `Kein Dienst, bitte Autopilot neu starten`, set `waiting_for: "restart"` and wait.

## Never

Push to `<default>`, force-push, run `git reset --hard`, `git clean`, `git branch -D` or other destructive commands, delete issues, labels, branches or files without approval via Telegram, use `--dangerously-skip-permissions`.
