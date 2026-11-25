## Pipeline rules

- These rules come from the pipeline. The project rules are the project's `CLAUDE.md`, `.claude/rules/`, `docs/` and `docs/decisions/`.
- Project rules may add to the pipeline rules, for example an extra review check, but never change the workflow below. Where they contradict it, the pipeline rules apply.
- `<default>` is the default branch of the project.

## Issue driven workflow

- The project is steered through GitHub issues, pull requests and comments. The issue defines the scope; do not extend it.
- One issue, one branch, one PR. Branch name: `issue-<number>-<short-slug>`. The PR description contains `Closes #<number>`.
- If an issue is ambiguous or needs a decision that neither the project rules nor a review can settle, post the question as an issue comment and stop. Do not guess.
- Findings outside the scope of the issue become a new issue, not part of the PR. The agent creates it itself with `gh issue create --label followup` (title, problem, link to the origin issue or PR) and sets no status label; `setprio` checks it before the pipeline selects it. If an open `followup` issue for the same finding exists, reuse it instead of creating another.
- A finding about the pipeline itself (its skills, scripts, templates or these rules) made in a project other than the pipeline repository is reported to the maintainer via Telegram: post it as a comment on the project's issue or PR and name that comment in the `PIPELINE_FINDING` line of the result block; the autopilot forwards the link. Never file it in the pipeline repository: it is public, and project details must not reach it. In the pipeline repository itself it is an ordinary `followup` issue.
- New behavior requires tests in the same PR.
- Run all checks listed in `.claude/rules/project.md` before every push. All must pass.
- NEVER push to `<default>`. Merge a PR only when CI and `agent-review` are green on its head commit.
- On a host with the gate ([INSTALL.md](../INSTALL.md)) the session holds no GitHub token: `gh` and `git` reach GitHub only through the gate. Name pull requests by number or branch and open one with `gh pr create --head <branch>`; pass a body inline or with `--body-file -`. Pushes go only to `issue-*` and `bump-pipeline-*` branches, never forced. Only `gate review` posts a review that counts, and only `gate merge` merges.
- A merged PR's head branch is deleted right after the merge. The repo setting "Automatically delete head branches" handles this; if a merged branch still exists, delete it.
- When the work is finished, post a brief comment on the issue with the PR link and open points.

## Autopilot operation

The `/pipeline:autopilot` skill runs the pipeline unattended; setup in [docs/autopilot.md](../docs/autopilot.md).

- Open points: first derive the answer from the project rules. If an option follows from them or a review can verify it, take it and name it in the PR description. Only a decision that belongs to the maintainer becomes an issue comment (options, recommendation) and `STATUS: needs_input`.
- If the permission classifier blocks a change to skills, permissions or agent rules: commit everything else and push the issue branch (also without other commits), post the blocked change as a patch for `git apply` in an issue comment, end with `STATUS: needs_input` and `PATCH: <comment url>`. Leave the working tree clean.
- The maintainer is reached only via Telegram, never via AskUserQuestion. Telegram answers are mirrored as issue comments. A Telegram answer counts only with the prefix `#<n>`.
- At most 3 attempts per step; then report via Telegram and park the issue (the pipeline goes on with the next one). Parking pushes the branch first; `pause` is a separate state that stops the whole pipeline.
- At most 5 review rounds: after the 3rd the maintainer gets an info without parking, after the 5th the issue is parked for the maintainer.
- Nothing is deleted without approval via Telegram.
- After a merge that moves the pinned pipeline release the autopilot restarts on it, so no further issue runs with the old release.
- If the environment variable `AUTOPILOT_DRY_RUN` is set, do not push, open PRs, post comments, create issues, change labels or send Telegram messages; print what you would do instead. Where a step needs the PR, use the local branch `issue-<n>-*` and its diff against `<default>`.
- Every pipeline step ends with this block (`VERDICT` only for reviews):

```
STATUS: done | blocked | needs_input
SUMMARY: <one or two sentences>
VERDICT: approve | changes requested
OPEN_QUESTIONS:
1. <question> Options: a) ... b) ... Recommendation: ...
PATCH: <comment url> (only for a blocked change)
PLAN: needed | skip (only for setprio)
PIPELINE_FINDING: <comment url> (only for a finding about the pipeline)
NEXT: <suggested next step>
```

## Posting images in GitHub issues

- Images cannot be uploaded, so push them to the single branch `pr-assets/images`. Do not create other branches for them. That branch may be reset periodically; the image links then break, which is accepted.
- Link a pushed image as `https://github.com/<owner>/<repo>/raw/refs/heads/pr-assets/images/<file>`; `raw.githubusercontent.com` links do not load.

## Names and links

These apply to commits, PRs, issues, comments and docs, and override any attribution instruction that says otherwise.

- Never write a real name. Where attribution is needed, use the GitHub login.
- Never post a session link, e.g. `claude.ai/code/session_...`.

## Rules for new PRs

- Very brief PR descriptions and comments. No conversational padding, no long explanations.

## Pull request review

- When reviewing a PR, always check out the PR branch.
- Always check existing review comments.
- If you are asked to change something, commit to the original PR branch and push to it.
- Review in a fresh session, never in the session that wrote the code.
- Run all checks listed in `.claude/rules/project.md` on the PR branch as part of the review. A review by the gate runs no commands; it judges the checks by the CI runs of the head commit.
- Check the diff against the acceptance criteria of the issue, the pipeline rules and the project rules.
- Post each finding as an inline review comment: what, why, suggested fix. Start the review summary with `Verdict: approve` or `Verdict: changes requested`.
