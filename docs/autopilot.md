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

- Eine Instanz je Projekt, jede unter einem eigenen Linux-Benutzer mit eigenem Telegram-Bot (`~/.claude/channels/telegram`) und eigenem systemd-User-Dienst. tmux-Session und Dienst heißen `autopilot-<Repository>`, der Name kommt aus der URL von `origin` ([`autopilot-name.sh`](../host/autopilot-name.sh)).
- Alle Skripte arbeiten auf dem Projekt im Arbeitsverzeichnis: Zustand in `.pipeline/`, Default-Branch aus `origin/HEAD` ([`default-branch.py`](../bin/default-branch.py)).
- Einrichtung im Projektverzeichnis: `.claude/skills/pipeline/host/install-service.sh [<label>]` schreibt `~/.config/systemd/user/autopilot-<Repository>.service` mit Projekt- und Plugin-Pfad und startet den Dienst. Beide Pfade dürfen nur `A-Za-z0-9._/-` enthalten.
- Dieses Repository kann nicht sein eigenes Submodul sein: `host/use-release.sh <tag>` checkt das Release als Worktree unter `.claude/skills/pipeline` aus (gitignored). Den Dienst danach mit `install-service.sh` aus diesem Worktree einrichten, damit er nicht den Arbeitsstand ausführt.
