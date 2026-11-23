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
