# Autopilot

Eine dauerhaft laufende Claude-Code-Session in tmux arbeitet die offenen Issues eines Projekts mit einem Auswahl-Label ab (Startargument, Default `ready`; Issues mit offenem Blocker werden übersprungen, Issues, die ein offenes Issue blockieren, zuerst, sonst niedrigste Nummer; siehe [`autopilot-poll.py`](../bin/autopilot-poll.py)). Ein anderes Label als `ready` bleibt am Issue ([Orchestrator](../skills/autopilot/SKILL.md), Regeln in [workflow.md](../rules/workflow.md#autopilot-operation)). Vor jeder Auswahl prüft der Fork [`setprio`](../skills/setprio/SKILL.md) Issues ohne Statuslabel (auch Folge-Issues) und setzt `ready` oder `question`; ein neues Folge-Issue meldet der Orchestrator per Telegram. Rückfragen und Permission-Prompts laufen über Telegram; einige Meldungen kommen mit Antwort-Buttons ([Skript](../bin/telegram-send.py), [ADR 0018](decisions/0018-telegram-buttons.md)).

Die Pfade unten gelten im Wurzelverzeichnis des Projekts; das Plugin liegt dort als Submodul unter `.claude/skills/pipeline`.

## Telegram-Befehle

Der Bot beantwortet `/help`, `/start` und `/status` selbst (Plugin), deshalb ohne Schrägstrich senden.

- `help`: diese Liste
- `status`: Issue, Schritt, Versuche, Label und geparkte Issues
- `pause`: hält nach dem laufenden Schritt an
- `weiter`: setzt nach Pause oder Fehler fort
- `/<task> <n>`: startet im Pausenzustand den Schritt (`plan-issue`, `issue`, `review-issue` oder `fix-review`); die Pipeline läuft danach bis zum Merge weiter, die Grenzen gelten unverändert; ein anderes aktuelles Issue wird geparkt
- `park #<n>`: parkt das aktuelle Issue, bei laufendem Schritt nach dessen Ende
- `stop #<n>`: bricht den laufenden Schritt ab und parkt das Issue
- `cleanup`: sichert in der Pause ungesicherte Änderungen als Commit auf dem lokalen Branch `cleanup/<n>-<Zeit>`, ohne Push
- `/verbose`: schaltet Meldungen zu jedem Schritt an oder aus
- `label <name>`: Auswahl-Label ab dem nächsten Issue, bis zum nächsten Start
- `#<n> <text>`: Antwort auf eine Rückfrage zu Issue n

## Einrichtung eines Projekts

- `host/init-project.sh <tag>` im Wurzelverzeichnis des Projekts, aus einem Klon dieses Repositorys: fügt das Release als Submodul unter `.claude/skills/pipeline` hinzu, kopiert die Vorlagen aus [`templates/`](../templates) (MIT-0), ohne vorhandene Dateien zu überschreiben, ergänzt `.gitignore`, legt mit [`create-labels.sh`](../host/create-labels.sh) die fehlenden Labels an und listet die Schritte, die von Hand bleiben (Commit, Trust-Dialog, Checks samt Allow-Regeln, Ruleset, automatisches Löschen der Head-Branches). Claude Code lädt das Plugin erst, wenn der Trust-Dialog im Projekt bestätigt ist.
- Die `CLAUDE.md` der Vorlage importiert die Pipeline-Regeln aus [`rules/workflow.md`](../rules/workflow.md). Projektregeln dürfen sie ergänzen, etwa um eine Review-Prüfung, aber den Ablauf nicht ändern.
- Die Vorlagen liegen unter `claude/` und `github/` statt `.claude/` und `.github/`, sonst lädt Claude Code sie als Regeln dieses Repositorys.
- `.claude/skills/pipeline/bin/check-project.py` gehört zu den Checks des Projekts: es schlägt fehl, wenn `.claude/settings.json` eine Deny-Regel der Vorlage fehlt oder `CLAUDE.md` die Zeile `@.claude/skills/pipeline/rules/workflow.md` nicht enthält. Plugins können keine Berechtigungen mitbringen, deshalb stehen sie in den Projekteinstellungen. Die Vorlage erlaubt nur die Befehle der Pipeline; jeder Check-Befehl braucht eine eigene Allow-Regel, sonst wartet jeder Lauf auf eine Freigabe.
- `.claude/skills/pipeline/host/bump.sh <tag>` öffnet einen PR, der das Submodul auf das Release setzt, mit den Release Notes und dem Label `infrastructure`, und kehrt danach zum vorherigen Branch zurück. `init-project.sh` setzt `submodule.recurse`, damit `git pull` und `git switch` das Submodul mitziehen und der Arbeitsbaum sauber bleibt; in anderen Klonen von Hand setzen.

## Einrichtung des Hosts

1. Als root: einen Linux-Benutzer je Projekt anlegen, `loginctl enable-linger <benutzer>`, `claude`, `git`, `gh`, `tmux` und `bun` installieren. `autopilot-start.sh` prüft das und nennt, was fehlt.
2. Als dieser Benutzer das Projekt klonen, `git submodule update --init && git config submodule.recurse true`, dann im Projekt `claude`, `/login` und den Ordner als vertrauenswürdig bestätigen. Ohne diese Bestätigung lädt Claude Code weder das Plugin noch die Allow-Liste aus `settings.json`.
3. GitHub: einen fine-grained Token nur für das Projekt-Repository anlegen, mit den Rechten Contents, Issues und Pull requests (Lesen und Schreiben) sowie Actions und Metadata (Lesen). `gh pr checks` braucht `checks=read`, das fine-grained Tokens nicht anbieten; der Autopilot nutzt deshalb `gh run`. Dann `gh auth login` und `gh auth setup-git`.
4. Telegram-Bot: bei [@BotFather](https://t.me/BotFather) `/newbot` senden und den Token kopieren.
5. In `claude`: `/plugin install telegram@claude-plugins-official` (User-Scope), dann `/telegram:configure <token>`. Der Token landet in `~/.claude/channels/telegram/.env`, nicht im Repository.
6. Session beenden und `claude --channels plugin:telegram@claude-plugins-official` starten. Dem Bot schreiben, den Code mit `/telegram:access pair <code>` bestätigen, danach `/telegram:access policy allowlist`.
7. Session beenden, `.claude/skills/pipeline/host/check-fork.sh` ausführen (Forks dürfen die Unterhaltung nicht sehen), dann `.claude/skills/pipeline/host/install-service.sh [<label>]`.
8. GitHub, Settings, Rules, Rulesets: ein aktives Ruleset auf dem Default-Branch ohne Bypass-Liste mit "Require a pull request" (0 Approvals) und "Require status checks" für die CI des Projekts und `agent-review`. Der Token hat kein Administration-Recht, deshalb von Hand. `agent-review` ([Workflow-Vorlage](../templates/github/workflows/agent-review.yml), [Skript](../bin/agent-review.py)) läuft nur bei Reviews, die mit `Verdict:` beginnen, und ist dann nur grün, wenn das letzte Review zum Head-Commit mit `Verdict: approve` beginnt. Ein übersprungener Lauf (z. B. nach einer Thread-Antwort) ist grün, aber kein Approve; der Orchestrator prüft deshalb mit dem Skript. In einem privaten Repository ohne Team-Plan setzt GitHub das Ruleset nicht durch; an seine Stelle tritt die [Merge-Regel](../rules/workflow.md#issue-driven-workflow), die der Orchestrator vor dem Merge prüft, samt offener Review-Threads ([Skript](../bin/open-review-threads.py)) und CI ([Skript](../bin/watch-ci.py)). Ist der Default-Branch weiter, mergt er ihn vorher in den Branch und lässt Review und Checks erneut laufen ([Skript](../bin/merge-default-branch.py)); bei einem Konflikt parkt er das Issue.

## Betrieb

| Aktion | Befehl |
|---|---|
| Starten | `.claude/skills/pipeline/host/autopilot-start.sh [label]` |
| Stoppen | `.claude/skills/pipeline/host/autopilot-stop.sh` |
| Status | `.claude/skills/pipeline/host/autopilot-status.sh` |
| Als Dienst | `.claude/skills/pipeline/host/install-service.sh [label]` (gilt ab dem nächsten Start des Dienstes) |
| Anhängen | `tmux attach -t autopilot-<Repository>` (lösen mit `Ctrl-b d`) |
| Fork-Isolation prüfen | `.claude/skills/pipeline/host/check-fork.sh` |
| Kennzahlen | `.claude/skills/pipeline/bin/pipeline-metrics.py summary` |

Die Session startet mit `--model sonnet --effort medium`; die Forks setzen Modell und Aufwand in ihrer Frontmatter. `CLAUDE_CODE_EFFORT_LEVEL` entfernt das Start-Skript, da es alle `effort`-Felder überschreibt. Steigen laut `pipeline-metrics.py` die Versuche bei `issue` oder die `review_rounds` deutlich, zuerst `issue` auf `opus`/`medium` zurückstellen.

Die Schritte laufen als Hintergrund-Forks (`background: true`), die Session beantwortet Telegram-Befehle also auch während eines Schritts; `pause` greift erst, wenn der Schritt fertig ist.

Wird der Dienst genutzt, nur über `systemctl --user start|stop autopilot-<Repository>` steuern. Endet Claude oder schlägt das Start-Skript fehl, startet der Dienst mit Backoff neu (bis 15 min). Auch `/exit` in der Session löst einen Neustart aus.

Bei einem Issue mit Label `infrastructure` schaltet der Autopilot Verbose selbst an und stellt nach dem Merge die vorige Einstellung wieder her. Nach einem Infrastruktur-Merge beendet sich die Session ([Skript](../bin/autopilot-restart.sh)), und der Dienst startet sie ohne wachsenden Backoff mit dem neuen Stand neu. Läuft kein Dienst, wartet der Autopilot auf einen Neustart von Hand. Nach jedem Merge wartet er auf den CI-Lauf auf dem Default-Branch; ist er rot, kommt der Link per Telegram und der Autopilot pausiert bis `weiter`. Bei einer Rückfrage sucht zuerst der Fork [`find-answer`](../skills/find-answer/SKILL.md) die Antwort in Issues, PRs und Doku; findet er sie, postet der Autopilot sie und setzt den Schritt fort. Bei einer Rückfrage ohne Treffer, einem Patch, `park`, `stop`, dem 3. Fehlversuch, der 5. Review-Runde und einem Merge-Konflikt parkt der Autopilot das Issue und nimmt das nächste; nach der Antwort nimmt er es an der nächsten Issue-Grenze wieder auf. Vor dem Parken und vor jedem Branch-Wechsel pusht er den Branch ([Skript](../bin/leave-branch.py)); bei ungesicherten Änderungen oder einem fehlgeschlagenen Push pausiert er, `cleanup` bzw. die Behebung und `weiter` setzen fort. Ein Kommentar des Maintainers auf dem Issue gilt als Antwort auf eine Rückfrage ([ADR 0009](decisions/0009-pipeline-events.md)), per Telegram nur mit Präfix `#<n>` (auch während einer Pause; das Issue läuft erst nach `weiter` weiter). Blockiert der Klassifikator eine Konfigurationsänderung, kommt per Telegram ein Link auf den Patch im Issue; sobald er auf dem Branch committet und gepusht ist, läuft der Autopilot weiter.

- Eine Instanz je Projekt, jede unter einem eigenen Linux-Benutzer mit eigenem Telegram-Bot (`~/.claude/channels/telegram`) und eigenem systemd-User-Dienst. tmux-Session und Dienst heißen `autopilot-<Repository>`, der Name kommt aus der URL von `origin` ([`autopilot-name.sh`](../host/autopilot-name.sh)). Zwei Projekte mit demselben Repository-Namen (etwa ein Fork und sein Upstream) können deshalb nicht unter demselben Benutzer laufen: `install-service.sh` und `autopilot-start.sh` brechen ab, wenn Dienst oder Session schon zu einem anderen Projektverzeichnis gehören.
- Alle Skripte arbeiten auf dem Projekt im Arbeitsverzeichnis: Zustand in `.pipeline/` des Projektwurzelverzeichnisses, auch aus einem Unterverzeichnis, Default-Branch aus `origin/HEAD` ([`default-branch.py`](../bin/default-branch.py)). `autopilot-start.sh`, `install-service.sh` und `check-fork.sh` brechen außerhalb des Projektwurzelverzeichnisses und im Submodul oder Release-Worktree des Plugins ab ([`require-project-root.sh`](../host/require-project-root.sh)).
- Der Hook gegen Pushes auf den Default-Branch liest `<remote>/HEAD` des Ziel-Remotes nur lokal. Fehlt es oder zeigt es auf einen gelöschten Branch, schützt er `main`, `master` und diesen Branch; `git remote set-head <remote> --auto` setzt es neu. Eine URL ordnet er über `git remote get-url` einem Remote zu; passt keines, schützt er die Default-Branches aller Remotes und `main` und `master`. Ohne Remote nimmt er das Push-Remote aus der git-Konfiguration, ohne Refspec das Ziel nach `remote.<remote>.push` und `push.default`. Ein Refspec ohne `:<dst>` folgt ebenfalls `remote.<remote>.push`; `-c`, `--config-env` und Variablen vor `git` zählen wie die Konfiguration. Ist der aktuelle Branch unbekannt (detached HEAD oder ein `cd`, dem der Hook nicht folgen kann), blockiert er einen Push ohne Ziel-Branch mit eigener Meldung; `~` und `$VAR` in `cd` und `git -C` löst er auf. Er findet Pushes auch hinter Shell-Schlüsselwörtern, `env`/`sudo`/`timeout`/`nice`/`xargs` (auch mit `env -C` oder `sudo -D`), Kommandosubstitution, `sh -c` und `bash -lc`, `eval` und git-Aliasen, nicht aber in Skriptdateien oder Shell-Funktionen. `PATH` vor `git` übernimmt er nicht für seine eigenen git-Aufrufe. Scheitert er selbst, blockiert er Befehle, die `push` enthalten.
- Einrichtung im Projektverzeichnis: `.claude/skills/pipeline/host/install-service.sh [<label>]` schreibt `~/.config/systemd/user/autopilot-<Repository>.service` mit Projekt- und Plugin-Pfad und startet den Dienst. Beide Pfade dürfen nur `A-Za-z0-9._/-` enthalten.
- Umstieg von Versionen mit einer Instanz je Host (Dienst und tmux-Session `autopilot`): nach dem Update `install-service.sh` im Projektverzeichnis ausführen. Es deaktiviert und löscht `autopilot.service`, beendet die Session `autopilot` und richtet `autopilot-<Repository>.service` ein. Gehört der alte Dienst zu einem anderen Projekt, bricht es ab und lässt ihn stehen. Bis dahin verweigert `autopilot-start.sh` den Start, solange die Session `autopilot` läuft.
- Dieses Repository kann nicht sein eigenes Submodul sein: `host/use-release.sh <tag>` checkt das Release als Worktree unter `.claude/skills/pipeline` aus (gitignored). Den Dienst danach mit `install-service.sh` aus diesem Worktree einrichten, damit er nicht den Arbeitsstand ausführt. Die Labels legt hier `host/create-labels.sh` an, Ruleset und automatisches Löschen der Head-Branches wie bei `init-project.sh` von Hand; das Ruleset verlangt die Status-Checks `checks` und `agent-review`.

## Fehlersuche

- `systemctl --user` meldet keinen Bus: `export XDG_RUNTIME_DIR=/run/user/$(id -u)`.
- Bot antwortet nicht: läuft die Session mit `--channels`? `tmux attach -t autopilot-<Repository>` zeigt die Startmeldung.
- Pipeline steht: `autopilot-status.sh` zeigt Zustand, Log und Bildschirm; offene Permission-Prompts erscheinen dort und in Telegram.
- Session- oder Wochenlimit: das Start-Skript setzt `CLAUDE_CODE_RETRY_WATCHDOG=1`, die Anfrage wartet bis zum Reset und der Schritt läuft danach weiter, ohne Versuch zu verbrauchen. In der Zeit beantwortet die Session keine Telegram-Nachrichten, sie bleiben bis zum Reset liegen. Die [Statuszeile](../host/autopilot-statusline.py) meldet das Limit einmal pro Reset-Zeit per Telegram; `autopilot-status.sh` zeigt es unter `--- limit`. Erscheint trotzdem das Limit-Menü: `tmux attach -t autopilot-<Repository>`, "Wait here, then continue automatically" wählen, nie Add funds oder Upgrade. Erschöpftes Guthaben oder ein Spend-Limit lässt die Anfrage sofort scheitern.
- Zustand zurücksetzen: Session stoppen, `.pipeline/state.json` prüfen oder anpassen, neu starten.
- Deny-Regeln in `.claude/settings.json` greifen nur auf Kommandotext, sie sind keine Sandbox. Pushes auf den Default-Branch blockiert zusätzlich der [Hook](../hooks/deny-default-branch-push.py), siehe Betrieb.
