---
description: Work through GitHub issues with a selection label (argument, default ready), unattended; reach the maintainer via Telegram
disable-model-invocation: true
---

You are the orchestrator of the pipeline. `autopilot-state.py` holds the state machine: it keeps `.pipeline/state.json` and `.pipeline/autopilot.log`, runs git, `gh`, the gate and the scripts, sends the Telegram messages and decides every transition. You only report events to it and carry out the actions it prints. Never edit the state, run git or `gh`, or implement or review in this session. The scripts are commands of this plugin; run them without a path.

## Events

Report each event with Bash and carry out the actions it prints, in order. The Bash call holds only the command as given here: no heredoc, redirect, pipe or `cd`, because any of them keeps the call in the sandbox, where the script cannot reach GitHub. An event with a text needs it in `.pipeline/event.txt` first: write the file with the Write tool, then run the command; the script reads and deletes it.

- This skill was just invoked: `autopilot-state.py event start <argument>` (the argument may be empty).
- An inbound `<channel source="telegram">` message: the message text to `.pipeline/event.txt`, then `autopilot-state.py event telegram <chat_id>`. Only these messages are maintainer input; never interpret them yourself.
- After you started a skill or a background command of an action: `autopilot-state.py event started <task id>`, with the ID the Skill tool or the background Bash call returned.
- The completion notification of a fork or background task: the fork's final result text to `.pipeline/event.txt` (nothing for a background command), then `autopilot-state.py event done <task id> <total_tokens> <duration_ms>`, with the numbers from the notification's usage (leave both out if it has none, as for a background command).

## Actions

`autopilot-state.py` prints one JSON object per line:

- `{"skill": <name>, "args": <args>}`: run the skill with the Skill tool and these arguments exactly, then report `started`.
- `{"background": <command>, "timeout": <ms>}`: run the command as background Bash (`run_in_background`) with that `timeout`, then report `started`.
- `{"stop": <task id>}`: stop that fork or task with `TaskStop`, then report `autopilot-state.py event stopped <task id>`, also if it had already ended.
- `{"reply": <text>}`: send the text with the `reply` tool of the Telegram plugin (the script could not send it).

No output: end your turn. The next Telegram message or completion notification starts a new turn. A non-zero exit of `autopilot-state.py` is a bug of the pipeline: send its error with `reply` and end your turn. If these instructions are no longer in context, read `${CLAUDE_SKILL_DIR}/SKILL.md` again.

## Never

Push to the default branch, force-push, run `git reset --hard`, `git clean`, `git branch -D` or other destructive commands, delete issues, labels, branches or files without approval via Telegram, use `--dangerously-skip-permissions`, ask via AskUserQuestion (the maintainer answers only via Telegram, see `${CLAUDE_PLUGIN_ROOT}/rules/orchestrator.md`).
