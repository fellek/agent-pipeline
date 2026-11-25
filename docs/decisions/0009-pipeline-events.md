# 0009 Pipeline-Events: Polling per `gh`

Status: angenommen

## Entscheidung

Der Orchestrator startet beim Warten genau einen [`autopilot-poll.py`](../../bin/autopilot-poll.py) als Hintergrund-Bash, der alle Ziele zugleich prüft: offene Issues mit dem Auswahl-Label und je geparktem Issue dessen Antwort oder Patch. Das Skript fragt alle 60 s per `gh api` ab: Issue-Kommentare mit einem Aufruf ab dem kleinsten Cursor, gefiltert nach dem Cursor `events_since` jedes Issues; für einen Patch den Head des Issue-Branches gegen den Commit im Cursor. Beim ersten Treffer gibt es die Events als JSON-Zeilen aus und endet; das Ende startet einen neuen Turn der Session. `check` fragt einmal ohne Warten ab, für Antworten, die kamen, während ein anderes Issue lief. Es zählen nur Kommentare des Maintainers (Login des Tokens, auch als `MEMBER` einer Organisation) ohne die Markierung der Pipeline auf geparkten Issues. Behandlung siehe [Orchestrator](../../bin/autopilot-state.py).

## Begründung

- Kein eingehender Port, kein Tunnel, kein zusätzlicher Dienst im LXC.
- Im Leerlauf laufen nur `gh`-Aufrufe, keine Modell-Turns.
- Beim Warten auf Kommentare ist der Cursor die GitHub-Serverzeit beim Beginn des Wartens und steht in `.pipeline/state.json`. Er überlebt einen Neustart, und eigene Kommentare des Autopiloten (gleicher Account) liegen immer davor.

## Bewusst ausgelassen

- `pull_request` und `check_suite`: erzeugt der Autopilot selbst; auf CI wartet er mit `gh run watch`.
- Triage jedes Kommentars nach #47.
- Kommentare, die der Maintainer schreibt, während der Orchestrator das vorige Event bearbeitet, gehen verloren: Der nächste Cursor liegt danach. Ein Cursor am letzten Event ginge inzwischen: Als Antwort zählt nur ein Kommentar des Logins des Tokens ohne die Markierung `<!-- pipeline -->`, die das Gate an jeden Kommentar der Pipeline hängt (#57).

## Verworfen

- Ein Poller pro geparktem Issue: mehrere Hintergrundprozesse, die alle vor eigenen Kommentaren gestoppt werden müssten.
- Self-hosted Runner im LXC mit `claude -p`: neue Session pro Event ohne den Zustand der laufenden; Runner als weiterer Dienst.
- Webhook-Channel als eigener MCP-Server: braucht eine erreichbare URL oder einen Tunnel.
- Wecken per `CronCreate` oder `/loop`: jeder Lauf ist ein Modell-Turn, auch ohne Event; Ablauf nach 7 Tagen.
- Monitor-Tool: endet nach höchstens 30 min. Plugin-Monitor: eigenes lokales Plugin, mehr Einrichtung.
