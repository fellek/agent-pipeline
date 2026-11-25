# Installation auf einem Linux-Host

Von einem frischen Linux-Host mit systemd zu einem laufenden Autopilot-Dienst für ein Projekt. Betrieb und Fehlersuche: [docs/autopilot.md](docs/autopilot.md).

Die Befehle nutzen den Projekt-Benutzer `autopilot`. Platzhalter in spitzen Klammern vor dem Einfügen ersetzen: `<tag>` ist das Release der Pipeline (etwa `v0.3.0`), `<owner>/<projekt>` das Projekt-Repository.

## 1. Benutzer und Werkzeuge

Mit sudo-Rechten:

1. Einen Linux-Benutzer je Projekt mit Linger anlegen, damit sein Dienst ohne Anmeldung läuft:

   ```
   sudo useradd -m -s /bin/bash autopilot
   sudo loginctl enable-linger autopilot
   ```

2. `git`, `gh`, `sudo`, `tmux`, `python3` (für die Skripte in `bin/`, `host/` und `hooks/`) sowie `bubblewrap` und `socat` (für die Bash-Sandbox) installieren, unter Debian und Ubuntu:

   ```
   sudo apt-get install -y git gh sudo tmux python3 bubblewrap socat
   ```

   Unter Ubuntu ab 24.04 braucht `bwrap` bei `kernel.apparmor_restrict_unprivileged_userns = 1` ein AppArmor-Profil, siehe die Sandbox-Doku von Claude Code.

Als Projekt-Benutzer (`sudo -iu autopilot`):

3. `claude` in der Version aus [`host/versions.sh`](host/versions.sh) und `bun` (für das Telegram-Plugin) installieren; sie landen in `~/.local/bin` und `~/.bun/bin`. Die Einstellung hält `claude` außerhalb des Autopiloten von Updates ab; der Autopilot setzt sie selbst. Eine neue Pipeline-Version kann eine andere Version verlangen, dann erneut `claude install <version>`.

   ```
   v=$(curl -fsSL https://raw.githubusercontent.com/fellek/agent-pipeline/<tag>/host/versions.sh | sed -n 's/^claude_code=//p')
   curl -fsSL https://claude.ai/install.sh | bash -s "$v"
   curl -fsSL https://bun.sh/install | bash
   mkdir -p ~/.claude && echo '{"env": {"DISABLE_AUTOUPDATER": "1"}}' > ~/.claude/settings.json
   export PATH="$HOME/.local/bin:$HOME/.bun/bin:$PATH"
   ```

   Die Installer tragen den `PATH` erst für neue Shells ein, die letzte Zeile gilt für die laufende. Ohne `bun` im `PATH` startet das Telegram-Plugin nicht.

4. Der Dienst sucht Programme nur in `~/.local/bin`, `~/.bun/bin`, `/usr/local/bin`, `/usr/bin` und `/bin` ([Unit](host/autopilot.service)). Alles, was woanders liegt, dort verlinken, etwa `ln -s /pfad/zu/programm ~/.local/bin/`.

`autopilot-start.sh` prüft `claude` und das Telegram-Plugin auf die Versionen aus `host/versions.sh`, `git`, `gh`, `sudo`, `tmux`, `bun`, `python3`, `bwrap`, `socat`, das Gate, dass der Benutzer keinen eigenen Token hat, das Ruleset des Default-Branches, das Telegram-Plugin samt Token und Linger und nennt, was fehlt.

## 2. GitHub und Gate (mit sudo-Rechten)

Den GitHub-Token hält nur das Gate ([`gate.py`](host/gate.py)), ein Linux-Benutzer `pipeline-gate`, den alle Projekte des Hosts teilen. Der Projekt-Benutzer hat keinen Token; `gh` und `git` erreichen GitHub über `sudo -u pipeline-gate /opt/pipeline/gate`. So kann die Session weder auf den Default-Branch pushen noch mergen oder ein Review fälschen, auch wenn GitHub kein Ruleset durchsetzt ([Merge und Review](docs/autopilot.md#merge-und-review)).

1. Einen fine-grained Token nur für das Projekt-Repository mit Ablaufdatum (etwa 90 Tage) anlegen, mit den Rechten Contents, Issues und Pull requests (Lesen und Schreiben) sowie Actions und Metadata (Lesen). `gh pr checks` braucht `checks=read`, das fine-grained Tokens nicht anbieten; der Autopilot nutzt deshalb `gh run`.
2. Dieses Repository auf dem Release-Tag klonen und das Gate installieren; `read` wartet auf den Token (unsichtbare Eingabe):

   ```
   git clone --branch <tag> https://github.com/fellek/agent-pipeline ~/agent-pipeline
   cd ~/agent-pipeline
   read -rs t && printf '%s\n' "$t" | sudo host/install-gate.sh autopilot <owner>/<projekt>
   ```

   Es legt `pipeline-gate` an, installiert das Gate unter `/opt/pipeline` (Eigentümer root), legt Token und Review-Schlüssel unter `/etc/pipeline-gate/projects/autopilot` ab (nur für `pipeline-gate` lesbar), erlaubt dem Benutzer per sudoers nur das Gate und leitet `gh` (`~/.local/bin/gh`) und `git` (`ext::`-Transport in `~/.gitconfig`) des Benutzers durch das Gate.
3. Einmal je Host Claude Code für `pipeline-gate` installieren und anmelden; damit laufen die Reviews. Im Klon aus 2.:

   ```
   v=$(. host/versions.sh && echo "$claude_code")
   sudo -u pipeline-gate -H bash -c "cd && curl -fsSL https://claude.ai/install.sh | bash -s $v"
   sudo -u pipeline-gate -H bash -c 'mkdir -p ~/.claude && echo "{\"env\": {\"DISABLE_AUTOUPDATER\": \"1\"}}" > ~/.claude/settings.json'
   sudo -u pipeline-gate -H bash -c 'cd && ~/.local/bin/claude'
   ```

   In `claude` dann `/login` ausführen und die Session beenden.
4. Im Repository unter Settings, Secrets and variables, Actions das Secret `PIPELINE_REVIEW_KEY` mit der Ausgabe von

   ```
   sudo cat /etc/pipeline-gate/projects/autopilot/review-key
   ```

   anlegen. Ohne Secret zählt `agent-review` ein Review nach seinem Text, mit Warnung.
5. Der Projekt-Benutzer darf keinen eigenen Token haben (kein `~/.config/gh/hosts.yml`, kein `GH_TOKEN`); `autopilot-start.sh` bricht sonst ab.

Vor Ablauf des Tokens einen neuen anlegen und wie in Schritt 2 an `install-gate.sh` geben, das ihn ersetzt; danach den alten auf GitHub löschen. Läuft er ab, scheitern alle Aufrufe des Gates: der Autopilot pausiert mit dem Fehler, im Leerlauf nach drei gescheiterten Abfragen des Pollers.

Nach einem Release, das `host/gate.py`, `host/gate-review.md`, `bin/attestation.py` oder `rules/workflow.md` ändert, `install-gate.sh` erneut ausführen (leere Eingabe behält den Token); `autopilot-start.sh` warnt, solange das installierte Gate abweicht:

```
cd ~/agent-pipeline && git fetch --tags && git checkout <tag>
read -rs t && printf '%s\n' "$t" | sudo host/install-gate.sh autopilot <owner>/<projekt>
```

## 3. Projekt (als Projekt-Benutzer)

Das Projekt klonen; `git` geht über das Gate aus 2. Der Pfad darf nur `A-Za-z0-9._/-` enthalten, sonst bricht `install-service.sh` ab. Alle folgenden Befehle laufen in diesem Verzeichnis.

```
git clone https://github.com/<owner>/<projekt> ~/<projekt>
cd ~/<projekt>
```

Dann eine der drei Varianten:

- **Neues Projekt**: zusätzlich dieses Repository klonen und `init-project.sh` im Projekt ausführen, nicht im Klon der Pipeline ([was es tut](docs/autopilot.md#einrichtung-eines-projekts)):

  ```
  git clone https://github.com/fellek/agent-pipeline ~/agent-pipeline
  cd ~/<projekt>
  ~/agent-pipeline/host/init-project.sh <tag>
  ```

  Danach die Schritte abarbeiten, die es am Ende listet: Commit, Trust-Dialog (siehe 4.), Checks in `.claude/rules/project.md` und in der CI, deren Allow-Regeln in `.claude/settings.json`, Ruleset und automatisches Löschen der Head-Branches (siehe 5.).
- **Projekt, das die Pipeline schon enthält**:

  ```
  git submodule update --init && git config submodule.recurse true
  ```

- **Dieses Repository**: es kann nicht sein eigenes Submodul sein, `init-project.sh` bricht hier ab. `use-release.sh` checkt das Release aus `.claude/pipeline-release` als Worktree unter `.claude/skills/pipeline` aus (gitignored), `create-labels.sh` legt die Labels an:

  ```
  host/use-release.sh
  host/create-labels.sh
  ```

## 4. Claude Code (als Projekt-Benutzer)

Im Projektverzeichnis `claude` starten, `/login` ausführen und den Ordner als vertrauenswürdig bestätigen. Ohne diese Bestätigung lädt Claude Code weder das Plugin noch die Allow-Liste aus `.claude/settings.json`.

```
cd ~/<projekt> && claude
```

## 5. Repository-Einstellungen (im Browser)

Der Token hat kein Administration-Recht, deshalb von Hand:

1. Settings, General: "Automatically delete head branches" einschalten.
2. Settings, Rules, Rulesets: ein aktives Ruleset auf dem Default-Branch ohne Bypass-Liste mit "Require a pull request" (0 Approvals), "Require status checks" für die CI des Projekts und `agent-review` sowie blockierten Force-Pushes und Löschungen. Für dieses Repository heißen die Status-Checks `checks` und `agent-review`. `autopilot-start.sh` startet nicht, solange eine dieser Regeln fehlt; nur wenn GitHub für ein privates Repository gar keine Regeln meldet (ohne Plan, der Rulesets durchsetzt), warnt es per Telegram und startet. Was `agent-review` prüft und was ohne durchgesetztes Ruleset gilt: [Merge und Review](docs/autopilot.md#merge-und-review).

## 6. Telegram (als Projekt-Benutzer)

1. Bei [@BotFather](https://t.me/BotFather) `/newbot` senden und den Token kopieren. Jedes Projekt braucht einen eigenen Bot.
2. Den Token in der Shell ablegen, nie in `claude` eintippen: dort stünde er im Transkript, und die Sandbox lässt `/telegram:configure` nicht nach `~/.claude/channels` schreiben. `read` wartet auf den Token (unsichtbare Eingabe):

   ```
   mkdir -p ~/.claude/channels/telegram
   read -rs t && (umask 077; printf 'TELEGRAM_BOT_TOKEN=%s\n' "$t" > ~/.claude/channels/telegram/.env)
   ```

   Dann in `claude` das Plugin installieren (User-Scope; es installiert die Version, die der Marketplace gerade führt, `autopilot-start.sh` verlangt die aus `host/versions.sh`):

   ```
   /plugin install telegram@claude-plugins-official
   ```

3. Session beenden und mit dem Kanal neu starten:

   ```
   claude --channels plugin:telegram@claude-plugins-official
   ```

   Dem Bot schreiben; er antwortet mit einem Code. Die Sandbox sperrt `~/.claude/channels` absichtlich, damit die Session weder den Token liest noch Absender freischaltet; `/telegram:access` scheitert deshalb. In einer zweiten Shell mit dem Code statt `<code>` freigeben; das trägt den Absender wie `/telegram:access pair` ein und setzt die Policy auf `allowlist`, damit nur der Maintainer den Bot erreicht:

   ```
   python3 - <code> <<'EOF'
   import json, pathlib, sys, time
   d = pathlib.Path.home() / ".claude/channels/telegram"
   f = d / "access.json"
   a = json.loads(f.read_text())
   p = a.get("pending", {}).pop(sys.argv[1], None)
   if not p or p["expiresAt"] < time.time() * 1000:
       sys.exit("Code unbekannt oder abgelaufen, dem Bot erneut schreiben")
   if p["senderId"] not in a.setdefault("allowFrom", []):
       a["allowFrom"].append(p["senderId"])
   a["dmPolicy"] = "allowlist"
   f.write_text(json.dumps(a, indent=2) + "\n")
   (d / "approved").mkdir(exist_ok=True)
   (d / "approved" / p["senderId"]).write_text(p["chatId"])
   print("freigegeben:", p["senderId"])
   EOF
   ```

4. Session beenden.

## 7. Dienst (als Projekt-Benutzer, im Projektverzeichnis)

1. Prüfen, dass Forks die Unterhaltung nicht sehen; die Ausgabe muss `OK: forked skill is isolated` sein:

   ```
   .claude/skills/pipeline/host/check-fork.sh
   ```

2. Den systemd-User-Dienst `~/.config/systemd/user/autopilot-<Repository>.service` schreiben und starten; der Autopilot nimmt Issues mit dem GitHub-Label `ready`; nur für ein anderes Auswahl-Label `install-service.sh <label>` aufrufen:

   ```
   .claude/skills/pipeline/host/install-service.sh
   ```

   Dazu kommen ein Alarm bei jedem Fehlschlag des Dienstes (`-alert.service` über `OnFailure=`) und ein Watchdog alle 15 Minuten (`-watchdog.timer`), die beide über `telegram-send.py` melden ([`autopilot-watchdog.py`](host/autopilot-watchdog.py)). Für dieses Repository aus dem Release-Worktree aufrufen, damit der Dienst nicht den Arbeitsstand ausführt.

## 8. Prüfen

Zustand, Log und Bildschirm der Session; dann der Dienst, der `active (running)` zeigen muss. Bei Problemen: [Fehlersuche](docs/autopilot.md#fehlersuche).

```
.claude/skills/pipeline/host/autopilot-status.sh
XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user status 'autopilot-*'
```

Dem Bot `status` senden (ohne Schrägstrich); die Antwort nennt Issue, Schritt und Label.

## Weiteres Projekt auf demselben Host

Für jedes weitere Projekt einen eigenen Linux-Benutzer mit Linger anlegen (1.1) und in allen Befehlen `autopilot` durch seinen Namen ersetzen. Dann als dieser Benutzer `claude` und `bun` installieren (1.3) und alle weiteren Schritte mit eigenem Token (`install-gate.sh` für diesen Benutzer, das Gate selbst bleibt geteilt), eigenem Review-Schlüssel und eigenem Telegram-Bot wiederholen; jeder Benutzer hat seinen eigenen Dienst ([Betrieb](docs/autopilot.md#betrieb)). Schritt 2.3 entfällt.
