# Autopilot

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

## Betrieb

- Eine Instanz je Projekt, jede unter einem eigenen Linux-Benutzer mit eigenem Telegram-Bot (`~/.claude/channels/telegram`) und eigenem systemd-User-Dienst. tmux-Session und Dienst heißen `autopilot-<Repository>`, der Name kommt aus der URL von `origin` ([`autopilot-name.sh`](../host/autopilot-name.sh)). Zwei Projekte mit demselben Repository-Namen (etwa ein Fork und sein Upstream) können deshalb nicht unter demselben Benutzer laufen: `install-service.sh` und `autopilot-start.sh` brechen ab, wenn Dienst oder Session schon zu einem anderen Projektverzeichnis gehören.
- Alle Skripte arbeiten auf dem Projekt im Arbeitsverzeichnis: Zustand in `.pipeline/` des Projektwurzelverzeichnisses, auch aus einem Unterverzeichnis, Default-Branch aus `origin/HEAD` ([`default-branch.py`](../bin/default-branch.py)). `autopilot-start.sh`, `install-service.sh` und `check-fork.sh` brechen außerhalb des Projektwurzelverzeichnisses und im Submodul oder Release-Worktree des Plugins ab ([`require-project-root.sh`](../host/require-project-root.sh)).
- Der Hook gegen Pushes auf den Default-Branch liest `<remote>/HEAD` des Ziel-Remotes nur lokal. Fehlt es oder zeigt es auf einen gelöschten Branch, schützt er `main`, `master` und diesen Branch; `git remote set-head <remote> --auto` setzt es neu. Eine URL ordnet er über `git remote get-url` einem Remote zu; passt keines, schützt er die Default-Branches aller Remotes und `main` und `master`. Ohne Remote nimmt er das Push-Remote aus der git-Konfiguration, ohne Refspec das Ziel nach `remote.<remote>.push` und `push.default`. Ein Refspec ohne `:<dst>` folgt ebenfalls `remote.<remote>.push`; `-c`, `--config-env` und Variablen vor `git` zählen wie die Konfiguration. Ist der aktuelle Branch unbekannt (detached HEAD oder ein `cd`, dem der Hook nicht folgen kann), blockiert er einen Push ohne Ziel-Branch mit eigener Meldung; `~` und `$VAR` in `cd` und `git -C` löst er auf. Er findet Pushes auch hinter Shell-Schlüsselwörtern, `env`/`sudo`/`timeout`/`nice`/`xargs` (auch mit `env -C` oder `sudo -D`), Kommandosubstitution, `sh -c` und `bash -lc`, `eval` und git-Aliasen, nicht aber in Skriptdateien oder Shell-Funktionen. `PATH` vor `git` übernimmt er nicht für seine eigenen git-Aufrufe. Scheitert er selbst, blockiert er Befehle, die `push` enthalten.
- Einrichtung im Projektverzeichnis: `.claude/skills/pipeline/host/install-service.sh [<label>]` schreibt `~/.config/systemd/user/autopilot-<Repository>.service` mit Projekt- und Plugin-Pfad und startet den Dienst. Beide Pfade dürfen nur `A-Za-z0-9._/-` enthalten.
- Umstieg von Versionen mit einer Instanz je Host (Dienst und tmux-Session `autopilot`): nach dem Update `install-service.sh` im Projektverzeichnis ausführen. Es deaktiviert und löscht `autopilot.service`, beendet die Session `autopilot` und richtet `autopilot-<Repository>.service` ein. Gehört der alte Dienst zu einem anderen Projekt, bricht es ab und lässt ihn stehen. Bis dahin verweigert `autopilot-start.sh` den Start, solange die Session `autopilot` läuft.
- Dieses Repository kann nicht sein eigenes Submodul sein: `host/use-release.sh <tag>` checkt das Release als Worktree unter `.claude/skills/pipeline` aus (gitignored). Den Dienst danach mit `install-service.sh` aus diesem Worktree einrichten, damit er nicht den Arbeitsstand ausführt.
