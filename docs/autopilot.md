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
- `update`: ohne aktuelles Issue; öffnet den PR auf das neueste Pipeline-Release oder startet nach dessen Merge auf ihm neu
- `#<n> <text>`: Antwort auf eine Rückfrage zu Issue n

## Einrichtung eines Projekts

Installation des Hosts und Einrichtung eines Projekts Schritt für Schritt: [INSTALL.md](../INSTALL.md).

- `host/init-project.sh <tag>` fügt das Release als Submodul unter `.claude/skills/pipeline` hinzu, kopiert die Vorlagen aus [`templates/`](../templates) (MIT-0), ohne vorhandene Dateien zu überschreiben, ergänzt `.gitignore` und legt mit [`create-labels.sh`](../host/create-labels.sh) die fehlenden Labels an.
- Projekte, die die Vorlage schon kopiert haben, übernehmen `agent-review-sync.yml` und den Wegfall von `pull_request_review` in `agent-review.yml` von Hand, da `init-project.sh` nichts überschreibt und `bump.sh` keine Vorlagen kopiert.
- Die `CLAUDE.md` der Vorlage importiert die Pipeline-Regeln aus [`rules/workflow.md`](../rules/workflow.md). Projektregeln dürfen sie ergänzen, etwa um eine Review-Prüfung, aber den Ablauf nicht ändern. Skills und Agents lesen die Pipeline-Regeln direkt aus dem Plugin, sie gelten also auch ohne Import immer in der Fassung ihres Releases; der Import bringt sie in interaktive Sessions.
- Die Vorlagen liegen unter `claude/` und `github/` statt `.claude/` und `.github/`, sonst lädt Claude Code sie als Regeln dieses Repositorys.
- `.claude/skills/pipeline/bin/check-project.py` gehört zu den Checks des Projekts: es schlägt fehl, wenn `.claude/settings.json` eine Deny-Regel der Vorlage fehlt oder weder `CLAUDE.md` noch `.claude/CLAUDE.md` eine `@`-Zeile enthält, deren Pfad relativ zur Datei auf `.claude/skills/pipeline/rules/workflow.md` des Projekts zeigt, etwa `@.claude/skills/pipeline/rules/workflow.md` in `CLAUDE.md`. Geprüft wird nur der Pfad, nicht ob die Datei existiert. Plugins können keine Berechtigungen mitbringen, deshalb stehen sie in den Projekteinstellungen. Die Vorlage erlaubt nur die Befehle der Pipeline; jeder Check-Befehl braucht eine eigene Allow-Regel, sonst wartet jeder Lauf auf eine Freigabe.
- Dateien der Pipeline (Skills, Agents, Hook, `bin/`, `rules/workflow.md`) gelten nur aus dem gepinnten Release, Projektregeln (`CLAUDE.md`, `.claude/rules/`, `.claude/settings.json`) aus dem Arbeitsbaum nach Merge und Neustart. Ein Projekt pinnt das Release über den Gitlink des Submoduls, dieses Repository über den Tag in `.claude/pipeline-release`, den `host/use-release.sh` auscheckt; der Pin ändert sich nur per PR. Fehlt das Release oder liegt es auf einem anderen Commit, lädt Claude Code ohne Meldung keine Pipeline. Deshalb ruft ein `SessionStart`-Hook in `.claude/settings.json` [`check-release.sh`](../host/check-release.sh) auf, und die Session beginnt mit einer Warnung; `check-project.py` verlangt diesen Hook.
- Update-Routine: [`update-pipeline.sh`](../host/update-pipeline.sh) sucht das neueste Release der Pipeline und öffnet mit `bump.sh` den PR darauf; ist der Pin schon dort, ändert es nichts. Nach dem Merge des PRs startet der Autopilot vor dem nächsten Issue auf dem neuen Release neu, oder sofort auf `update`. Der Telegram-Befehl `update` führt beides aus.
- `.claude/skills/pipeline/host/bump.sh <tag>` öffnet einen PR, der das Submodul (in diesem Repository `.claude/pipeline-release`) auf das Release setzt, mit den Release Notes und dem Label `infrastructure`, und kehrt danach zum vorherigen Branch zurück. `init-project.sh` setzt `submodule.recurse`, damit `git pull` und `git switch` das Submodul mitziehen und der Arbeitsbaum sauber bleibt; in anderen Klonen von Hand setzen.

## Merge und Review

`agent-review` ([Workflow-Vorlage](../templates/github/workflows/agent-review.yml), [Skript](../bin/agent-review.py)) läuft bei jedem Push und ist nur grün, wenn das letzte Review zum Head-Commit mit `Verdict: approve` beginnt; nach jedem Review führt [`agent-review-sync.yml`](../templates/github/workflows/agent-review-sync.yml) diesen Lauf erneut aus, wenn sein Ergebnis nicht zum Verdict passt ([0025](decisions/0025-agent-review-sync.md)). Der Orchestrator gleicht vor dem Merge ebenfalls mit dem Skript ab. In einem privaten Repository ohne Team-Plan setzt GitHub das Ruleset nicht durch; an seine Stelle tritt die [Merge-Regel](../rules/workflow.md#issue-driven-workflow), die der Orchestrator vor dem Merge prüft, samt offener Review-Threads ([Skript](../bin/open-review-threads.py)) und CI ([Skript](../bin/watch-ci.py)). Ist der Default-Branch weiter, mergt er ihn vorher in den Branch und lässt Review und Checks erneut laufen ([Skript](../bin/merge-default-branch.py)); bei einem Konflikt parkt er das Issue.

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

Bei einem Issue mit Label `infrastructure` schaltet der Autopilot Verbose selbst an und stellt nach dem Merge die vorige Einstellung wieder her. Hat ein Merge den Pin des Pipeline-Releases verschoben (geprüft vor jedem Issue) ([`release-changed.sh`](../bin/release-changed.sh)), beendet sich die Session ([Skript](../bin/autopilot-restart.sh)), in diesem Repository nach `use-release.sh`, und der Dienst startet sie ohne wachsenden Backoff auf dem neuen Release neu. Läuft kein Dienst, wartet der Autopilot auf einen Neustart von Hand. Nach jedem Merge wartet er auf den CI-Lauf auf dem Default-Branch; ist er rot, kommt der Link per Telegram und der Autopilot pausiert bis `weiter`. Bei einer Rückfrage sucht zuerst der Fork [`find-answer`](../skills/find-answer/SKILL.md) die Antwort in Issues, PRs und Doku; findet er sie, postet der Autopilot sie und setzt den Schritt fort. Bei einer Rückfrage ohne Treffer, einem Patch, `park`, `stop`, dem 3. Fehlversuch, der 5. Review-Runde und einem Merge-Konflikt parkt der Autopilot das Issue und nimmt das nächste; nach der Antwort nimmt er es an der nächsten Issue-Grenze wieder auf. Vor dem Parken und vor jedem Branch-Wechsel pusht er den Branch ([Skript](../bin/leave-branch.py)); bei ungesicherten Änderungen oder einem fehlgeschlagenen Push pausiert er, `cleanup` bzw. die Behebung und `weiter` setzen fort. Ein Kommentar des Maintainers auf dem Issue gilt als Antwort auf eine Rückfrage ([ADR 0009](decisions/0009-pipeline-events.md)), per Telegram nur mit Präfix `#<n>` (auch während einer Pause; das Issue läuft erst nach `weiter` weiter). Blockiert der Klassifikator eine Konfigurationsänderung, kommt per Telegram ein Link auf den Patch im Issue; sobald er auf dem Branch committet und gepusht ist, läuft der Autopilot weiter.

- Eine Instanz je Projekt, jede unter einem eigenen Linux-Benutzer mit eigenem Telegram-Bot (`~/.claude/channels/telegram`) und eigenem systemd-User-Dienst. tmux-Session und Dienst heißen `autopilot-<Repository>`, der Name kommt aus der URL von `origin` ([`autopilot-name.sh`](../host/autopilot-name.sh)). Zwei Projekte mit demselben Repository-Namen (etwa ein Fork und sein Upstream) können deshalb nicht unter demselben Benutzer laufen: `install-service.sh` und `autopilot-start.sh` brechen ab, wenn Dienst oder Session schon zu einem anderen Projektverzeichnis gehören.
- Alle Skripte arbeiten auf dem Projekt im Arbeitsverzeichnis: Zustand in `.pipeline/` des Projektwurzelverzeichnisses, auch aus einem Unterverzeichnis, Default-Branch aus `origin/HEAD` ([`default-branch.py`](../bin/default-branch.py)). `autopilot-start.sh`, `install-service.sh` und `check-fork.sh` brechen außerhalb des Projektwurzelverzeichnisses und im Submodul oder Release-Worktree des Plugins ab ([`require-project-root.sh`](../host/require-project-root.sh)).
- Der Hook gegen Pushes auf den Default-Branch liest `<remote>/HEAD` des Ziel-Remotes nur lokal. Fehlt es oder zeigt es auf einen gelöschten Branch, schützt er `main`, `master` und diesen Branch; `git remote set-head <remote> --auto` setzt es neu. Eine URL ordnet er über `git remote get-url` einem Remote zu; passt keines, schützt er die Default-Branches aller Remotes und `main` und `master`. Ohne Remote nimmt er das Push-Remote aus der git-Konfiguration, ohne Refspec das Ziel nach `remote.<remote>.push` und `push.default`. Ein Refspec ohne `:<dst>` folgt ebenfalls `remote.<remote>.push`; `-c`, `--config-env` und Variablen vor `git` zählen wie die Konfiguration. Ist der aktuelle Branch unbekannt (detached HEAD oder ein `cd`, dem der Hook nicht folgen kann), blockiert er einen Push ohne Ziel-Branch mit eigener Meldung; `~` und `$VAR` in `cd` und `git -C` löst er auf. Er findet Pushes auch hinter Shell-Schlüsselwörtern, `env`/`sudo`/`timeout`/`nice`/`xargs` (auch mit `env -C` oder `sudo -D`), Kommandosubstitution, `sh -c` und `bash -lc`, `eval` und git-Aliasen, nicht aber in Skriptdateien oder Shell-Funktionen. `PATH` vor `git` übernimmt er nicht für seine eigenen git-Aufrufe. Scheitert er selbst, blockiert er Befehle, die `push` enthalten.
- Umstieg von Versionen mit einer Instanz je Host (Dienst und tmux-Session `autopilot`): nach dem Update `install-service.sh` im Projektverzeichnis ausführen. Es deaktiviert und löscht `autopilot.service`, beendet die Session `autopilot` und richtet `autopilot-<Repository>.service` ein. Gehört der alte Dienst zu einem anderen Projekt, bricht es ab und lässt ihn stehen. Bis dahin verweigert `autopilot-start.sh` den Start, solange die Session `autopilot` läuft.

## Fehlersuche

- `systemctl --user` meldet keinen Bus: `export XDG_RUNTIME_DIR=/run/user/$(id -u)`.
- Bot antwortet nicht: läuft die Session mit `--channels`? `tmux attach -t autopilot-<Repository>` zeigt die Startmeldung.
- Pipeline steht: `autopilot-status.sh` zeigt Zustand, Log und Bildschirm; offene Permission-Prompts erscheinen dort und in Telegram.
- Session- oder Wochenlimit: das Start-Skript setzt `CLAUDE_CODE_RETRY_WATCHDOG=1`, die Anfrage wartet bis zum Reset und der Schritt läuft danach weiter, ohne Versuch zu verbrauchen. In der Zeit beantwortet die Session keine Telegram-Nachrichten, sie bleiben bis zum Reset liegen. Die [Statuszeile](../host/autopilot-statusline.py) meldet das Limit einmal pro Reset-Zeit per Telegram; `autopilot-status.sh` zeigt es unter `--- limit`. Erscheint trotzdem das Limit-Menü: `tmux attach -t autopilot-<Repository>`, "Wait here, then continue automatically" wählen, nie Add funds oder Upgrade. Erschöpftes Guthaben oder ein Spend-Limit lässt die Anfrage sofort scheitern.
- Zustand zurücksetzen: Session stoppen, `.pipeline/state.json` prüfen oder anpassen, neu starten.
- Deny-Regeln in `.claude/settings.json` greifen nur auf Kommandotext, sie sind keine Sandbox. Pushes auf den Default-Branch blockiert zusätzlich der [Hook](../hooks/deny-default-branch-push.py), siehe Betrieb.
