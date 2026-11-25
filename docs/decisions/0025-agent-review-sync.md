# 0025 agent-review: Lauf des Pushs nach dem Review neu ausführen

Status: angenommen

## Entscheidung

- Das Ruleset wertet jeden `agent-review`-Lauf auf dem Head-Commit für sich: Ein grüner Lauf des Reviews ersetzt den roten Lauf des Pushs nicht, nur ein Re-Run desselben Laufs tut das (#20, #21).
- Der Check hat deshalb eine Quelle: [`agent-review.yml`](../../.github/workflows/agent-review.yml) läuft nur auf `pull_request`.
- [`agent-review-sync.yml`](../../.github/workflows/agent-review-sync.yml) läuft auf `pull_request_review` (`submitted`, `dismissed`) und ruft `agent-review.py sync` auf: Es wartet auf den letzten Lauf des Pushs auf dem Head-Commit und führt ihn erneut aus, wenn sein Ergebnis nicht zum Verdict passt. Der Re-Run liest die Reviews neu, wird also nach einem Approve grün und nach Changes requested oder einem verworfenen Approve rot. Der Job heißt `agent-review-sync`, damit kein zweiter Check `agent-review` entsteht; ohne `cancel-in-progress`, damit kein Sync abgebrochen wird.
- Antworten auf Threads ändern das Verdict nicht und lösen keinen Re-Run aus.
- `sync` schlägt nur fehl, wenn der Lauf danach nicht zum Verdict passt. Ein roter Lauf ohne Approve ist der richtige Zustand, sonst kostete jedes Changes requested und jede Thread-Antwort davor einen roten `agent-review-sync`-Lauf samt Mail. Der Orchestrator wertet deshalb die Ausgabe `green` aus.
- Der Orchestrator ruft in Schritt 7 `agent-review.py await` auf: wie `sync`, aber ohne Re-Run, weil sein Token Actions nur liest (#63). Passt der Lauf nicht zum Verdict, wartet er bis zu 10 Minuten auf den Re-Run des Workflows; fehlt der Workflow, scheitert der Schritt mit `red`. Ein abgelehntes `gh pr merge` ist ein Fehlversuch und schließt weder Issue noch setzt es den Zustand zurück.

## Verworfen

- Nur der Orchestrator führt den Lauf neu aus: Nach einem Approve bleibt der Check rot, ein manueller Merge braucht einen manuellen Re-Run, und Changes requested nach einem grünen Lauf lässt den Check grün.
- Nur auf Reviews mit Verdict laufen, ohne `pull_request`: Ein übersprungener Lauf nach einer Thread-Antwort zählt als Erfolg, das Ruleset ließe einen Head-Commit ohne Approve durch; Changes requested und danach Approve auf demselben Commit bliebe blockiert.
