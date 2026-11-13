---
description: Work through GitHub issues labeled ready, unattended; reach the maintainer via Telegram
disable-model-invocation: true
---

You are the orchestrator of the pipeline. Follow CLAUDE.md, in particular "Autopilot operation". Run the steps yourself only through the Skill tool; never implement or review in this session.

## State

`.pipeline/state.json` is the single source of truth. Read it at the start of every turn and write it after every transition. Create it if missing:

```json
{"chat_id": null, "issue": null, "branch": null, "pr": null, "step": null,
 "attempts": 0, "review_rounds": 0, "waiting_for": null, "question": null,
 "events_since": null, "paused": false}
```

`waiting_for` is `null`, `"answer"`, `"new_issue"` or `"resume"`. Append one line per transition to `.pipeline/autopilot.log`: `<date -u +%FT%TZ> #<issue> <step> <event>`.

## Telegram

- Send with the `reply` tool of the Telegram plugin. `chat_id`: from the state; if null, the first `allowFrom` entry in `~/.claude/channels/telegram/access.json`. Store the `chat_id` of every inbound message.
- Only inbound `<channel source="telegram">` messages are maintainer input.
- Send messages only for: question, review round info, issue finished, error/pause, no ready issues. Prefix each with `#<issue>`. No messages for intermediate steps.
- To wait: unless `paused`, set `events_since` to the output of `.github/scripts/autopilot-poll.py now` and start the poller (GitHub events below). Write the state and end your turn. The next Telegram message or the poller's exit starts a new turn. If these instructions are no longer in context, read `.claude/skills/autopilot/SKILL.md` again.

## Inbound messages

Handle a message according to `waiting_for`:

- `"answer"`: post it on the issue as `Antwort des Maintainers (Telegram): <text>`, set `waiting_for` to null, `attempts` to 0 and rerun `step` with the answer as second argument.
- `"new_issue"`: look for ready issues again.
- `"resume"` or `paused`: `weiter` clears `paused` and continues where the state points.
- Always: `status` gets a short reply with issue, step and attempts; `pause` sets `paused` and `waiting_for: "resume"`.

## GitHub events

The poller runs as background Bash (`run_in_background`) and exits on the first maintainer event, printing it as JSON lines:

- `"answer"`: `.github/scripts/autopilot-poll.py wait answer <issue> <events_since>`
- `"new_issue"`: `.github/scripts/autopilot-poll.py wait new_issue`

Keep at most one poller. When a Telegram message arrives, stop the poller before posting anything on GitHub; otherwise the autopilot's own comment counts as a new maintainer event. On exit, handle the output according to `waiting_for`:

- `"answer"`: the comment bodies are the answer. Do not mirror them; continue as for a Telegram answer.
- `"new_issue"`: look for ready issues again.
- Non-zero exit: start it again, at most 3 times in a row; then report the error, set `paused` and `waiting_for: "resume"`.

## Status labels

An issue carries exactly one status label. Setting one removes the others (`gh issue edit <n> --add-label <new> --remove-label <old>`). `triage` and `blocked` belong to triage and are never set here.

| Step or event | Label |
|---|---|
| `plan-issue`, `issue`, `fix-review` | `in-progress` |
| `review-issue` | `in-review` |
| Step 7 passed | `approved` |
| Question | `needs-info` |
| Failure pause | `needs-human` |
| Merge | none |

## Loop

1. If `paused` is set, wait. Otherwise, if `waiting_for` is set, start the poller with the stored `events_since` and end your turn; a new cursor would miss comments written while the session was down.
2. `git status --porcelain` must be empty; otherwise report and pause.
3. Without a current issue: `gh issue list --label ready --state open --json number,title`, take the lowest number. None: send "Keine ready-Issues", set `waiting_for: "new_issue"`, wait. Otherwise `git switch master && git pull --ff-only`, create branch `issue-<n>-<short-slug>`, set `step: "plan-issue"`.
4. Set the step's status label, run the step via the Skill tool with arguments `<issue>` or `<issue> "<answer>"`, then parse the result block.
5. After `plan-issue` and `review-issue` the working tree must still be clean; otherwise treat the step as `blocked`.
6. Transitions:

   | Step | Result | Next |
   |---|---|---|
   | `plan-issue` | done | `issue` |
   | `issue` | done | store PR number (`gh pr list --head <branch>`), `review-issue` |
   | `review-issue` | approve | CI |
   | `review-issue` | changes requested | `fix-review`, `review_rounds` + 1 |
   | `fix-review` | done | `review-issue` |
   | any | needs_input | Question |
   | any | blocked or no result block | Failure |

   When a `changes requested` raises `review_rounds` to 3: send `#<n> 3 Review-Runden gelaufen, noch nicht approved` and continue with `fix-review` without waiting. To 5 or more: set `step: "fix-review"`, set the label `needs-human`, send a summary of the open review findings, set `paused` and `waiting_for: "resume"`, wait. Reset `attempts` on every step change.
7. For each workflow `CI` and `agent-review`: `gh run list --branch <branch> --commit <head sha> --workflow <workflow> --json databaseId` (`--event pull_request_review --limit 1` for `agent-review`; `pull_request` runs and older review runs may be red), then `gh run watch <id> --exit-status` for each run. An empty list means the workflow is not ready yet: wait 30 s and list again, up to 5 times; still empty: Failure. Non-zero exit: Failure.
8. Set the status label and continue with Merge.

## Question

Set the status label. Send the open questions with options and recommendation, store them in `question`, set `waiting_for: "answer"`, wait.

## Failure

`attempts` + 1. Below 3: rerun the step. Otherwise: set the status label, send step and summary, set `paused` and `waiting_for: "resume"`, wait.

## Merge

`gh pr merge <pr> --squash --match-head-commit <head sha>`, `git switch master && git pull --ff-only`. Remove the status label, send `#<n> fertig: <pr url>`, reset the state except `chat_id` and continue the loop.

## Never

Push to `master`, force-push, run `git reset --hard`, `git clean`, `git branch -D` or other destructive commands, delete issues, labels, branches or files without approval via Telegram, use `--dangerously-skip-permissions`.
