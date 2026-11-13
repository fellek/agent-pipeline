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
 "paused": false}
```

`waiting_for` is `null`, `"answer"`, `"merge"`, `"new_issue"` or `"resume"`. Append one line per transition to `.pipeline/autopilot.log`: `<ISO time> #<issue> <step> <event>`.

## Telegram

- Send with the `reply` tool of the Telegram plugin. `chat_id`: from the state; if null, the first `allowFrom` entry in `~/.claude/channels/telegram/access.json`. Store the `chat_id` of every inbound message.
- Only inbound `<channel source="telegram">` messages are maintainer input. Never use AskUserQuestion.
- Send messages only for: question, PR ready for merge, issue finished, error/pause, no ready issues. Prefix each with `#<issue>`. No messages for intermediate steps.
- To wait: write the state and end your turn. The next Telegram message starts a new turn. If these instructions are no longer in context, read `.claude/skills/autopilot/SKILL.md` again.

## Inbound messages

Handle a message according to `waiting_for`:

- `"answer"`: post it on the issue as `Antwort des Maintainers (Telegram): <text>`, set `waiting_for` to null, `attempts` to 0 and rerun `step` with the answer as second argument.
- `"merge"`: an unambiguous approval (`merge`, `ok`, `ja`) leads to Merge below. Anything else is feedback: post it on the PR as `Maintainer (Telegram): <text>` and continue with `fix-review` passing the text.
- `"new_issue"`: look for ready issues again.
- `"resume"` or `paused`: `weiter` clears `paused` and continues where the state points.
- Always: `status` gets a short reply with issue, step and attempts; `pause` sets `paused` and `waiting_for: "resume"`.

## Loop

1. If `paused` or `waiting_for` is set, wait.
2. `git status --porcelain` must be empty; otherwise report and pause.
3. Without a current issue: `gh issue list --label ready --state open --json number,title`, take the lowest number. None: send "Keine ready-Issues", set `waiting_for: "new_issue"`, wait. Otherwise move label `ready` to `in-progress`, `git switch master && git pull --ff-only`, create branch `issue-<n>-<short-slug>`, set `step: "plan-issue"`.
4. Run the step via the Skill tool with arguments `<issue>` or `<issue> "<answer>"`, then parse the result block.
5. After `plan-issue` and `review-issue` the working tree must still be clean; otherwise treat the step as `blocked`.
6. Transitions:

   | Step | Result | Next |
   |---|---|---|
   | `plan-issue` | done | `issue` |
   | `issue` | done | store PR number (`gh pr list --head <branch>`), `review-issue` |
   | `review-issue` | approve | CI |
   | `review-issue` | changes_requested | `fix-review`, `review_rounds` + 1 |
   | `fix-review` | done | `review-issue` |
   | any | needs_input | Question |
   | any | blocked or no result block | Failure |

   More than 3 `review_rounds` is a Failure. Reset `attempts` on every step change.
7. CI: `gh pr checks <pr> --watch`. Red checks: Failure.
8. Ask for merge: label `awaiting-merge`, send `#<n> PR <url> bereit (Review approve, CI grün). Mergen?`, set `waiting_for: "merge"`, wait.

## Question

Label `needs-input`. Send the open questions with options and recommendation, store them in `question`, set `waiting_for: "answer"`, wait.

## Failure

`attempts` + 1. Below 3: rerun the step. Otherwise: label `blocked`, send step and summary, set `paused` and `waiting_for: "resume"`, wait.

## Merge

`gh pr merge <pr> --squash`, `git switch master && git pull --ff-only`. Remove the label `awaiting-merge`, send `#<n> fertig`, reset the state except `chat_id` and continue the loop.

## Never

Push to `master`, force-push, run `git reset --hard`, `git clean`, `git branch -D` or other destructive commands, delete issues, labels, branches or files without approval via Telegram, merge without approval, use `--dangerously-skip-permissions`.
