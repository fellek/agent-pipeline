# 0009 Pipeline-Events: Polling per `gh`

Status: angenommen

## Entscheidung

Der Orchestrator startet beim Warten [`autopilot-poll.py`](../../.github/scripts/autopilot-poll.py) als Hintergrund-Bash. Das Skript fragt alle 60 s per `gh api` Issue-Kommentare seit dem Cursor `events_since` ab, im Wartezustand `merge` zusätzlich Reviews und Review-Kommentare des PR, im Wartezustand `new_issue` stattdessen offene Issues mit `ready`. Beim ersten Treffer gibt es ihn als JSON-Zeilen aus und endet; das Ende startet einen neuen Turn der Session. Es zählen nur Kommentare mit `author_association == OWNER` auf dem aktuellen Issue oder PR. Behandlung siehe [Orchestrator](../../.claude/skills/autopilot/SKILL.md#github-events).

## Begründung

- Kein eingehender Port, kein Tunnel, kein zusätzlicher Dienst im LXC.
- Im Leerlauf laufen nur `gh`-Aufrufe, keine Modell-Turns.
- Der Cursor ist die GitHub-Serverzeit beim Beginn des Wartens und steht in `.pipeline/state.json`. Er überlebt einen Neustart, und eigene Kommentare des Autopiloten (gleicher Account) liegen immer davor.
- Merge-Freigaben kommen weiter nur per Telegram; ein PR-Kommentar ist Feedback.

## Bewusst ausgelassen

- `pull_request` und `check_suite`: erzeugt der Autopilot selbst; auf CI wartet er mit `gh run watch`.
- Triage jedes Kommentars nach #47.
- Kommentare, die der Maintainer schreibt, während der Orchestrator das vorige Event bearbeitet, gehen verloren: Der nächste Cursor liegt danach. Ein Cursor am letzten Event würde eigene OWNER-Kommentare des Autopiloten melden (#49).

## Verworfen

- Self-hosted Runner im LXC mit `claude -p`: neue Session pro Event ohne den Zustand der laufenden; Runner als weiterer Dienst.
- Webhook-Channel als eigener MCP-Server: braucht eine erreichbare URL oder einen Tunnel.
- Wecken per `CronCreate` oder `/loop`: jeder Lauf ist ein Modell-Turn, auch ohne Event; Ablauf nach 7 Tagen.
- Monitor-Tool: endet nach höchstens 30 min. Plugin-Monitor: eigenes lokales Plugin, mehr Einrichtung.
