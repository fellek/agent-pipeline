import json
import subprocess
from pathlib import Path

import pytest
from conftest import ROOT, copy_scripts, project, write_executable

VERSIONS = dict(
    line.split("=", 1)
    for line in (ROOT / "host" / "versions.sh").read_text().splitlines()
    if "=" in line
)


def plugins(version=VERSIONS["telegram_plugin"]):
    return json.dumps([{"id": "telegram@claude-plugins-official", "version": version}])


@pytest.fixture
def run_start(tmp_path, app):
    scripts = tmp_path / "plugin" / "host"
    stubs = tmp_path / "bin"
    stubs.mkdir()
    copy_scripts(
        scripts,
        "autopilot-start.sh",
        "autopilot-name.sh",
        "require-project-root.sh",
        "versions.sh",
    )
    tmux_args = tmp_path / "tmux_args"
    write_executable(
        stubs / "tmux",
        '[ "$1" = has-session ] && { [ "$3" = "=${RUNNING_SESSION-}" ]; exit; }; '
        '[ "$1" = display-message ] && { echo "${SESSION_PATH-}"; exit; }; '
        f'printf "%s\\n" "$@" > {tmux_args}'
        '; shift 6; "$@"',
    )
    effort_level = tmp_path / "effort_level"
    watchdog = tmp_path / "watchdog"
    updater = tmp_path / "updater"
    write_executable(
        stubs / "claude",
        f"""case "$1" in
  --version) echo "${{CLAUDE_VERSION:-{VERSIONS["claude_code"]}}} (Claude Code)" ;;
  plugin) [ "$2" = validate ] && {{ echo "$3" > {tmp_path}/validated; printf '%s\n' "Validating $3" "  > ${{VALIDATE_OUT-ok}}" "Plugin directory checks" "  > README" "× Validation failed"; exit "${{VALIDATE_EXIT-0}}"; }}
    printf '%s\n' "${{PLUGINS:-$DEFAULT_PLUGINS}}" ;;
  *) echo "${{CLAUDE_CODE_EFFORT_LEVEL-unset}}" > {effort_level}
     echo "${{CLAUDE_CODE_RETRY_WATCHDOG-unset}}" > {watchdog}
     echo "${{DISABLE_AUTOUPDATER-unset}}" > {updater} ;;
esac""",
    )
    write_executable(stubs / "loginctl", "echo yes")
    plugin_bin = tmp_path / "plugin" / "bin"
    plugin_bin.mkdir()
    write_executable(plugin_bin / "default-branch.py", "echo main")
    write_executable(
        scripts / "check-ruleset.py",
        'echo "$1" > "$RULESET_ARGS"; [ -z "${RULESET_OUT-}" ] || echo "$RULESET_OUT"'
        "; exit ${RULESET_EXIT-0}",
    )
    write_executable(
        scripts / "check-release.sh",
        'echo "${RELEASE_OUT-}"; exit "${RELEASE_EXIT-0}"',
    )
    write_executable(plugin_bin / "telegram-send.py", 'cat > "$TELEGRAM_OUT"')
    write_executable(plugin_bin / "gate", 'exit "${GATE_EXIT-0}"')
    copy_scripts(scripts, "gate.py")
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / ".gitconfig").write_text(
        "[user]\n\tname = autopilot\n\temail = autopilot@host\n"
    )
    for cmd in ("gh", "sudo", "bun", "bwrap", "socat"):
        write_executable(stubs / cmd, "exit 0")

    def run(*args, env=None, cwd=app):
        tmux_args.unlink(missing_ok=True)
        result = subprocess.run(
            [str(scripts / "autopilot-start.sh"), *args],
            cwd=cwd,
            env={
                "PATH": f"{stubs}:/usr/bin:/bin",
                "TELEGRAM_BOT_TOKEN": "t",
                "RULESET_ARGS": str(tmp_path / "ruleset_args"),
                "TELEGRAM_OUT": str(tmp_path / "telegram"),
                "PIPELINE_GATE": str(scripts / "gate.py"),
                "HOME": str(tmp_path / "home"),
                "DEFAULT_PLUGINS": plugins(),
                **(env or {}),
            },
            check=False,
            capture_output=True,
            text=True,
        )
        lines = tmux_args.read_text().splitlines() if tmux_args.exists() else []
        return result, lines, effort_level, watchdog, updater

    return run


@pytest.mark.parametrize(
    ("args", "prompt"),
    [((), "/pipeline:autopilot ready"), (("batch-1",), "/pipeline:autopilot batch-1")],
)
def test_starts_autopilot_with_label(run_start, args, prompt):
    result, tmux_args, *_ = run_start(*args)
    assert result.returncode == 0, result.stderr
    assert tmux_args[-1] == prompt


@pytest.mark.parametrize("args", [("batch 1",), ("batch", "1")])
def test_rejects_label_with_whitespace(run_start, args):
    result, tmux_args, *_ = run_start(*args)
    assert result.returncode == 1
    assert "whitespace" in result.stderr
    assert tmux_args == []


def test_starts_session_with_model_and_effort(run_start):
    result, tmux_args, *_ = run_start()
    assert result.returncode == 0, result.stderr
    command = " ".join(tmux_args)
    assert "--model sonnet --effort medium" in command


def test_removes_effort_level_from_session_environment(run_start):
    result, _, effort_level, *_ = run_start(env={"CLAUDE_CODE_EFFORT_LEVEL": "high"})
    assert result.returncode == 0, result.stderr
    assert effort_level.read_text().strip() == "unset"


def test_starts_session_with_retry_watchdog(run_start):
    result, _, _, watchdog, _ = run_start()
    assert result.returncode == 0, result.stderr
    assert watchdog.read_text().strip() == "1"


def test_registers_status_line_for_session_only(run_start):
    result, tmux_args, *_ = run_start()
    assert result.returncode == 0, result.stderr
    settings = json.loads(tmux_args[tmux_args.index("--settings") + 1])
    status_line = settings["statusLine"]
    assert status_line["command"].endswith("/plugin/host/autopilot-statusline.py")
    assert status_line["command"].startswith("/")
    assert status_line["refreshInterval"] == 60


def session_settings(tmux_args):
    return json.loads(tmux_args[tmux_args.index("--settings") + 1])


def test_session_refuses_hosts_outside_the_allowlist(run_start):
    result, tmux_args, *_ = run_start()
    assert result.returncode == 0, result.stderr
    assert session_settings(tmux_args)["sandbox"]["network"]["strictAllowlist"] is True


def test_session_hides_the_bot_token_from_sandboxed_commands(run_start):
    result, tmux_args, *_ = run_start()
    assert result.returncode == 0, result.stderr
    assert session_settings(tmux_args)["sandbox"]["credentials"]["envVars"] == [
        {"name": "TELEGRAM_BOT_TOKEN", "mode": "deny"}
    ]


def test_session_denies_a_web_fetch_prompt(run_start):
    result, tmux_args, *_ = run_start()
    assert result.returncode == 0, result.stderr
    [entry] = session_settings(tmux_args)["hooks"]["PermissionRequest"]
    assert entry["matcher"] == "WebFetch"
    [hook] = entry["hooks"]
    assert hook["command"].endswith("/plugin/host/deny-fetch-prompt.sh")
    hook_result = subprocess.run(
        [str(ROOT / "host" / "deny-fetch-prompt.sh")],
        input="{}",
        capture_output=True,
        text=True,
        check=True,
    )
    output = json.loads(hook_result.stdout)["hookSpecificOutput"]
    assert output["hookEventName"] == "PermissionRequest"
    assert output["decision"]["behavior"] == "deny"
    assert output["decision"]["message"]


def test_starts_session_named_after_repository_in_project(run_start, tmp_path):
    result, tmux_args, *_ = run_start()
    assert result.returncode == 0, result.stderr
    assert tmux_args[:6] == [
        "new-session",
        "-d",
        "-s",
        "autopilot-app",
        "-c",
        str(tmp_path / "app"),
    ]
    assert (tmp_path / "app" / ".pipeline").is_dir()


def test_two_projects_get_separate_sessions(run_start, tmp_path):
    site = project(tmp_path / "site", "https://github.com/o/site.git")
    _, app_args, *_ = run_start()
    _, site_args, *_ = run_start(cwd=site)
    assert app_args[3] == "autopilot-app"
    assert site_args[3:6] == ["autopilot-site", "-c", str(site)]


def test_rejects_subdirectory_of_project(run_start, app):
    (app / "docs").mkdir()
    result, tmux_args, *_ = run_start(cwd=app / "docs")
    assert result.returncode == 1
    assert "project root" in result.stderr
    assert tmux_args == []
    assert not (app / "docs" / ".pipeline").exists()


def test_refuses_while_old_session_runs(run_start, app):
    result, tmux_args, *_ = run_start(env={"RUNNING_SESSION": "autopilot"})
    assert result.returncode == 1
    assert "old session autopilot" in result.stderr
    assert tmux_args == []


def test_running_session_of_project_shows_status(run_start, tmp_path, app):
    write_executable(tmp_path / "plugin" / "host" / "autopilot-status.sh", "echo up")
    result, tmux_args, *_ = run_start(
        env={"RUNNING_SESSION": "autopilot-app", "SESSION_PATH": str(app)}
    )
    assert (result.returncode, result.stdout) == (0, "up\n")
    assert tmux_args == []


def test_refuses_session_of_other_project_with_same_name(run_start, tmp_path):
    fork = project(tmp_path / "fork", "https://github.com/other/app.git")
    result, tmux_args, *_ = run_start(
        env={"RUNNING_SESSION": "autopilot-app", "SESSION_PATH": str(fork)}
    )
    assert result.returncode == 1
    assert f"session autopilot-app runs {fork}" in result.stderr
    assert tmux_args == []


def test_fails_without_python3_and_points_to_install(run_start, tmp_path):
    # python3 sits in /usr/bin next to the tools the script needs.
    system = tmp_path / "system"
    system.mkdir()
    for path in Path("/usr/bin").iterdir():
        if not path.name.startswith("python"):
            (system / path.name).symlink_to(path)
    result, tmux_args, *_ = run_start(env={"PATH": f"{tmp_path / 'bin'}:{system}"})
    assert result.returncode == 1
    assert "python3 is missing" in result.stderr
    assert result.stderr.rstrip().endswith("/INSTALL.md")
    assert tmux_args == []


def test_checks_ruleset_of_default_branch(run_start, tmp_path):
    result, *_ = run_start()
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "ruleset_args").read_text() == "main\n"
    assert not (tmp_path / "telegram").exists()


def test_refuses_to_start_without_required_rules(run_start):
    result, tmux_args, *_ = run_start(
        env={
            "RULESET_OUT": "the default branch main lacks the rules: x",
            "RULESET_EXIT": "1",
        }
    )
    assert result.returncode == 1
    assert "lacks the rules: x" in result.stderr
    assert tmux_args == []


def test_warns_via_telegram_and_starts_when_rules_are_not_enforced(run_start, tmp_path):
    warning = "Warning: the default branch main lacks the rules: x."
    result, tmux_args, *_ = run_start(env={"RULESET_OUT": warning})
    assert result.returncode == 0, result.stderr
    assert warning in result.stderr
    assert (tmp_path / "telegram").read_text() == warning + "\n"
    assert tmux_args[-1] == "/pipeline:autopilot ready"


@pytest.mark.parametrize("cmd", ["bwrap", "socat"])
def test_fails_without_sandbox_tools(run_start, tmp_path, cmd):
    (tmp_path / "bin" / cmd).unlink()
    system = tmp_path / "system"
    system.mkdir()
    for path in Path("/usr/bin").iterdir():
        if path.name != cmd:
            (system / path.name).symlink_to(path)
    result, *_ = run_start(env={"PATH": f"{tmp_path / 'bin'}:{system}"})
    assert result.returncode == 1
    assert f"{cmd} is missing" in result.stderr


def test_refuses_without_git_identity(run_start, tmp_path):
    (tmp_path / "home" / ".gitconfig").write_text("[user]\n\tname = autopilot\n")

    result, lines, *_ = run_start()

    assert result.returncode == 1
    assert "git has no user.email, run:" in result.stderr
    assert not lines


def test_refuses_without_working_gate(run_start):
    result, tmux_args, *_ = run_start(env={"GATE_EXIT": "1"})
    assert result.returncode == 1
    assert "the gate does not reach the repository" in result.stderr
    assert tmux_args == []


@pytest.mark.parametrize("variable", ["GH_TOKEN", "GITHUB_TOKEN"])
def test_refuses_with_own_token_in_environment(run_start, variable):
    result, _tmux_args, *_ = run_start(env={variable: "t"})
    assert result.returncode == 1
    assert "holds a GitHub token of its own" in result.stderr


def test_refuses_with_own_gh_login(run_start, tmp_path):
    hosts = tmp_path / "home" / ".config" / "gh" / "hosts.yml"
    hosts.parent.mkdir(parents=True)
    hosts.write_text("github.com:\n    oauth_token: t\n")
    result, _tmux_args, *_ = run_start()
    assert result.returncode == 1
    assert "holds a GitHub token of its own" in result.stderr


def test_warns_about_a_stale_gate(run_start, tmp_path):
    stale = tmp_path / "stale-gate"
    stale.write_text("old")
    result, tmux_args, *_ = run_start(env={"PIPELINE_GATE": str(stale)})
    assert result.returncode == 0, result.stderr
    assert "differs from host/gate.py" in (tmp_path / "telegram").read_text()
    assert tmux_args[-1] == "/pipeline:autopilot ready"


def test_raises_the_bash_timeouts_of_the_session(run_start):
    result, tmux_args, *_ = run_start()
    assert result.returncode == 0, result.stderr
    assert "BASH_DEFAULT_TIMEOUT_MS=600000" in tmux_args
    assert "BASH_MAX_TIMEOUT_MS=3600000" in tmux_args


def test_session_runs_without_the_auto_updater(run_start):
    result, *_, updater = run_start()

    assert result.returncode == 0, result.stderr
    assert updater.read_text() == "1\n"


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"CLAUDE_VERSION": "2.1.999"}, "claude 2.1.999 is not"),
        ({"PLUGINS": plugins("0.0.8")}, "Telegram plugin 0.0.8 is not"),
        ({"PLUGINS": "[]"}, "Telegram plugin is not installed"),
    ],
    ids=["claude", "plugin", "no_plugin"],
)
def test_refuses_other_versions(run_start, env, message):
    result, tmux_args, *_ = run_start(env=env)

    assert result.returncode == 1
    assert message in result.stderr
    assert tmux_args == []


@pytest.mark.parametrize(
    "env",
    [{"CLAUDE_VERSION": "2.1.999"}, {"PLUGINS": plugins("0.0.8")}],
    ids=["claude", "plugin"],
)
def test_version_mismatch_reaches_telegram(run_start, tmp_path, env):
    result, *_ = run_start(env=env)

    assert result.returncode == 1
    assert "is not" in (tmp_path / "telegram").read_text()


def test_fails_with_message_when_plugin_list_fails(run_start):
    result, tmux_args, *_ = run_start(env={"PLUGINS": "not json"})

    assert result.returncode == 1
    assert "claude plugin list --json failed" in result.stderr
    assert "Traceback" not in result.stderr
    assert tmux_args == []


@pytest.mark.parametrize(
    ("env", "message"),
    [
        (
            {"RELEASE_EXIT": "1", "RELEASE_OUT": "Warning: tag v9 is not fetched"},
            "Warning: tag v9 is not fetched",
        ),
        (
            {"VALIDATE_EXIT": "1", "VALIDATE_OUT": "bad manifest"},
            "fails claude plugin validate: bad manifest\n",
        ),
    ],
    ids=["release", "validate"],
)
def test_broken_release_stops_the_start_with_a_message(
    run_start, tmp_path, env, message
):
    result, tmux_args, *_ = run_start(env=env)

    assert result.returncode == 1
    assert message in (tmp_path / "telegram").read_text()
    assert tmux_args == []


def test_validates_the_plugin_of_the_release(run_start, tmp_path):
    run_start()
    assert (tmp_path / "validated").read_text() == f"{tmp_path / 'plugin'}\n"
