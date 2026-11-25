# Installation auf einem Linux-Host

Von einem frischen Linux-Host mit systemd zu einem laufenden Autopilot-Dienst für ein Projekt. Betrieb und Fehlersuche: [docs/autopilot.md](docs/autopilot.md).

## 1. Benutzer und Werkzeuge

Als root:

1. Einen Linux-Benutzer je Projekt anlegen und `loginctl enable-linger <benutzer>` ausführen, damit sein Dienst ohne Anmeldung läuft.
2. `git`, `gh`, `sudo`, `tmux`, `python3` (für die Skripte in `bin/`, `host/` und `hooks/`) sowie `bubblewrap` und `socat` (für die Bash-Sandbox) installieren. Unter Ubuntu ab 24.04 braucht `bwrap` bei `kernel.apparmor_restrict_unprivileged_userns = 1` ein AppArmor-Profil, siehe die Sandbox-Doku von Claude Code.

Als Projekt-Benutzer:

3. `claude` (mindestens 2.1.239) und `bun` (für das Telegram-Plugin) mit ihren Installern installieren; sie landen in `~/.local/bin` und `~/.bun/bin`.
4. Der Dienst sucht Programme nur in `~/.local/bin`, `~/.bun/bin`, `/usr/local/bin`, `/usr/bin` und `/bin` ([Unit](host/autopilot.service)). Alles, was woanders liegt, dort verlinken.

`autopilot-start.sh` prüft `claude` samt Version, `git`, `gh`, `sudo`, `tmux`, `bun`, `python3`, `bwrap`, `socat`, das Gate, dass der Benutzer keinen eigenen Token hat, das Ruleset des Default-Branches, das Telegram-Plugin samt Token und Linger und nennt, was fehlt.

## 2. GitHub und Gate (als root)

Den GitHub-Token hält nur das Gate ([`gate.py`](host/gate.py)), ein Linux-Benutzer `pipeline-gate`, den alle Projekte des Hosts teilen. Der Projekt-Benutzer hat keinen Token; `gh` und `git` erreichen GitHub über `sudo -u pipeline-gate /opt/pipeline/gate`. So kann die Session weder auf den Default-Branch pushen noch mergen oder ein Review fälschen, auch wenn GitHub kein Ruleset durchsetzt ([Merge und Review](docs/autopilot.md#merge-und-review)).

1. Einen fine-grained Token nur für das Projekt-Repository anlegen, mit den Rechten Contents, Issues und Pull requests (Lesen und Schreiben) sowie Actions und Metadata (Lesen). `gh pr checks` braucht `checks=read`, das fine-grained Tokens nicht anbieten; der Autopilot nutzt deshalb `gh run`.
2. In einem Klon dieses Repositorys auf dem Release-Tag: `read -rs t && printf '%s\n' "$t" | host/install-gate.sh <benutzer> <owner>/<projekt>`. Es legt `pipeline-gate` an, installiert das Gate unter `/opt/pipeline` (Eigentümer root), legt Token und Review-Schlüssel unter `/etc/pipeline-gate/projects/<benutzer>` ab (nur für `pipeline-gate` lesbar), erlaubt dem Benutzer per sudoers nur das Gate und leitet `gh` (`~/.local/bin/gh`) und `git` (`ext::`-Transport in `~/.gitconfig`) des Benutzers durch das Gate.
3. Einmal je Host Claude Code für `pipeline-gate` installieren und anmelden (`sudo -u pipeline-gate -H ...`, dann `claude` und `/login`); damit laufen die Reviews.
4. Im Repository unter Settings, Secrets and variables, Actions das Secret `PIPELINE_REVIEW_KEY` mit dem Inhalt von `/etc/pipeline-gate/projects/<benutzer>/review-key` anlegen. Ohne Secret zählt `agent-review` ein Review nach seinem Text, mit Warnung.
5. Der Projekt-Benutzer darf keinen eigenen Token haben (kein `~/.config/gh/hosts.yml`, kein `GH_TOKEN`); `autopilot-start.sh` bricht sonst ab.

Nach einem Release, das `host/gate.py`, `host/gate-review.md`, `bin/attestation.py` oder `rules/workflow.md` ändert, `install-gate.sh` erneut ausführen (leere Eingabe behält den Token); `autopilot-start.sh` warnt, solange das installierte Gate abweicht.

## 3. Projekt (als Projekt-Benutzer)

Das Projekt klonen, etwa `git clone https://github.com/<owner>/<projekt> ~/<projekt>`; `git` geht über das Gate aus 2. Der Pfad darf nur `A-Za-z0-9._/-` enthalten, sonst bricht `install-service.sh` ab. Alle folgenden Befehle laufen in diesem Verzeichnis. Dann eine der drei Varianten:

- **Neues Projekt**: zusätzlich dieses Repository klonen, etwa `git clone https://github.com/fellek/agent-pipeline ~/agent-pipeline`, und im Projekt `~/agent-pipeline/host/init-project.sh <tag>` ausführen ([was es tut](docs/autopilot.md#einrichtung-eines-projekts)). Danach die Schritte abarbeiten, die es am Ende listet: Commit, Trust-Dialog (siehe 4.), Checks in `.claude/rules/project.md` und in der CI, deren Allow-Regeln in `.claude/settings.json`, Ruleset und automatisches Löschen der Head-Branches (siehe 5.).
- **Projekt, das die Pipeline schon enthält**: `git submodule update --init && git config submodule.recurse true`.
- **Dieses Repository**: es kann nicht sein eigenes Submodul sein. `host/use-release.sh` checkt das Release aus `.claude/pipeline-release` als Worktree unter `.claude/skills/pipeline` aus (gitignored). Die Labels legt `host/create-labels.sh` an.

## 4. Claude Code (als Projekt-Benutzer)

Im Projektverzeichnis `claude` starten, `/login` ausführen und den Ordner als vertrauenswürdig bestätigen. Ohne diese Bestätigung lädt Claude Code weder das Plugin noch die Allow-Liste aus `.claude/settings.json`.

## 5. Repository-Einstellungen (im Browser)

Der Token hat kein Administration-Recht, deshalb von Hand:

1. Settings, General: "Automatically delete head branches" einschalten.
2. Settings, Rules, Rulesets: ein aktives Ruleset auf dem Default-Branch ohne Bypass-Liste mit "Require a pull request" (0 Approvals), "Require status checks" für die CI des Projekts und `agent-review` sowie blockierten Force-Pushes und Löschungen. Für dieses Repository heißen die Status-Checks `checks` und `agent-review`. `autopilot-start.sh` startet nicht, solange eine dieser Regeln fehlt; nur wenn GitHub für ein privates Repository gar keine Regeln meldet (ohne Plan, der Rulesets durchsetzt), warnt es per Telegram und startet. Was `agent-review` prüft und was ohne durchgesetztes Ruleset gilt: [Merge und Review](docs/autopilot.md#merge-und-review).

## 6. Telegram (als Projekt-Benutzer)

1. Bei [@BotFather](https://t.me/BotFather) `/newbot` senden und den Token kopieren. Jedes Projekt braucht einen eigenen Bot.
2. In `claude`: `/plugin install telegram@claude-plugins-official` (User-Scope), dann `/telegram:configure <token>`. Der Token landet in `~/.claude/channels/telegram/.env`, nicht im Repository.
3. Session beenden und `claude --channels plugin:telegram@claude-plugins-official` starten. Dem Bot schreiben, den Code mit `/telegram:access pair <code>` bestätigen, danach `/telegram:access policy allowlist`, damit nur der Maintainer den Bot erreicht.
4. Session beenden.

## 7. Dienst (als Projekt-Benutzer, im Projektverzeichnis)

1. `.claude/skills/pipeline/host/check-fork.sh` muss `OK: forked skill is isolated` melden (Forks dürfen die Unterhaltung nicht sehen).
2. `.claude/skills/pipeline/host/install-service.sh [<label>]` schreibt den systemd-User-Dienst `~/.config/systemd/user/autopilot-<Repository>.service` und startet ihn; Default-Label `ready`. Für dieses Repository aus dem Release-Worktree aufrufen, damit der Dienst nicht den Arbeitsstand ausführt.

## 8. Prüfen

- `.claude/skills/pipeline/host/autopilot-status.sh` zeigt Zustand, Log und Bildschirm der Session.
- `systemctl --user status autopilot-<Repository>` zeigt den Dienst als `active (running)`. Bei Problemen: [Fehlersuche](docs/autopilot.md#fehlersuche).
- Dem Bot `status` senden (ohne Schrägstrich); die Antwort nennt Issue, Schritt und Label.

## Weiteres Projekt auf demselben Host

Für jedes weitere Projekt als root einen eigenen Linux-Benutzer mit Linger anlegen (1.1), dann als dieser Benutzer `claude` und `bun` installieren (1.3) und alle weiteren Schritte mit eigenem Token (`install-gate.sh` für diesen Benutzer, das Gate selbst bleibt geteilt), eigenem Review-Schlüssel und eigenem Telegram-Bot wiederholen; jeder Benutzer hat seinen eigenen Dienst ([Betrieb](docs/autopilot.md#betrieb)).
