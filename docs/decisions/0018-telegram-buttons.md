# 0018 Telegram: Antwort-Buttons

Status: angenommen

## Entscheidung

- Meldungen mit Antwortmöglichkeiten sendet der Orchestrator mit [`telegram-send.py`](../../bin/telegram-send.py) statt mit dem Tool `reply` des Plugins. Das Skript ruft `sendMessage` direkt auf und hängt die Buttons als Reply-Tastatur an (`one_time_keyboard`). Ein Druck sendet das Label als normale Nachricht, jedes Label ist also ein gültiger Befehl oder eine gültige Antwort. Welche Meldung welche Buttons bekommt, steht im Abschnitt Telegram des [Orchestrators](../../skills/autopilot/SKILL.md).
- Token und Aufruf liegen nur in diesem Skript; die Statuszeile ruft es für ihre Limit-Meldung auf.
- Schlägt das Skript fehl (z. B. Text über 4096 Zeichen), sendet der Orchestrator denselben Text ohne Buttons mit `reply`.
- Eine Antwort aus nur einem Optionsbuchstaben oder `Empfehlungen` erweitert der Orchestrator mit der gespeicherten Rückfrage, bevor er sie postet: `fix-review` liest nur PR-Kommentare, ein nacktes `a` wäre dort ohne Bezug.
- Veraltete Tastaturen bleiben stehen, bis die nächste kommt. Ein späterer Druck trifft die bestehenden Prüfungen (`wartet nicht auf eine Antwort`, `ist nicht das aktuelle Issue`) und richtet nichts an.

## Verworfen

- Inline-Buttons: Das Plugin (`server.ts` 0.0.7) zeigt sie nur für Freigaben und quittiert andere Callbacks, ohne sie weiterzugeben.
- Eigener Plugin-Fork: Wartungsaufwand für einen Komfortgewinn.
- Gemeinsames Python-Modul für Statuszeile und Skript: neues Importmuster in `bin/` und `host/`, ein Subprozess pro seltener Limit-Meldung ist billiger.
