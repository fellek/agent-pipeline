# agent-pipeline

Claude Code plugin that plans, implements, reviews and merges the GitHub issues of a project, unattended via an autopilot the maintainer reaches over Telegram.

## Install

There is no marketplace install: a project includes the plugin as the git submodule `.claude/skills/pipeline`, so its gitlink pins one release and Claude Code loads the skills, agents and hook from there. In the project root:

```
git clone https://github.com/fellek/agent-pipeline ~/agent-pipeline
~/agent-pipeline/host/init-project.sh <tag>
```

`init-project.sh` adds the submodule at `<tag>` and copies the templates; [INSTALL.md](INSTALL.md) covers the host and the remaining steps.

## Docs

- Rules for the agents: [rules/workflow.md](rules/workflow.md)
- Install on a Linux host: [INSTALL.md](INSTALL.md)
- Project setup, operation and troubleshooting: [docs/autopilot.md](docs/autopilot.md)
- Templates for a new project: [templates/](templates)
