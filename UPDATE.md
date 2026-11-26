# Release und Update

Wie eine neue Version der Pipeline entsteht und auf einen Host kommt: erst der automatische Weg, dann zu jedem Schritt der Weg von Hand. Einrichtung: [INSTALL.md](INSTALL.md).

Wie in INSTALL.md heißt der Projekt-Benutzer `autopilot`, sein Dienst `autopilot-<Repository>`. Platzhalter: `<tag>` ist das Release (etwa `v0.3.3`), `<pr>` die Nummer des Bump-PRs, `<sha>` sein Head-Commit. "root" heißt eine root-Shell auf dem Host, sonst `sudo` davor.

## Ablauf

| # | Schritt | Automatisch | Wer von Hand |
|---|---|---|---|
| 1 | Version erhöhen | nein | Maintainer, PR |
| 2 | Release anlegen | Workflow `release` nach dem Start | Maintainer, Browser |
| 3 | Bump-PR öffnen | Timer `pipeline-update@autopilot` | Telegram `update` |
| 4 | Ankündigung | Timer, per Telegram | entfällt |
| 5 | 12 Stunden warten, Veto möglich | Timer | Bump-PR schließen |
| 6 | Approve und Merge | Timer | root |
| 7 | Gate installieren | Timer | root |
| 8 | Claude Code nachziehen | Timer | root |
| 9 | Autopilot neu starten | Autopilot selbst | Telegram `update` |

Der Timer läuft als root alle 15 Minuten (`/opt/pipeline/update-host --auto autopilot`), eingerichtet von `install-gate.sh`. Er nimmt nur das neueste veröffentlichte stabile Release, dessen Tag auf `main` der Pipeline liegt, und nur einen Bump-PR, der allein den Pin auf diesen Tag setzt. Fehler meldet er einmal per Telegram; Details: `journalctl -u pipeline-update@autopilot`.

## 1. Version erhöhen

Ein PR, der `version` in [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json) erhöht, durch Gate-Review und Merge wie jeder PR dieses Repositorys. Von Hand auf dem Host als root, nachdem die CI des PRs grün ist:

```
sudo -u autopilot sudo -n -u pipeline-gate /opt/pipeline/gate review <pr> <sha>
sudo -u autopilot sudo -n -u pipeline-gate /opt/pipeline/gate merge <pr> <sha>
```

Statt des Reviews durch das Gate geht auch das Verdict des Maintainers: `sudo -u pipeline-gate /opt/pipeline/gate review --manual autopilot <pr> <sha> approve`.

## 2. Release anlegen

Im Browser: Actions, Workflow `release`, "Run workflow" auf `main`. `tag` ist `v` plus die Version aus 1., `notes` die Update-Hinweise (was ein Projekt von Hand anpassen muss), leer lassen, wenn es keine gibt. Der Workflow lässt die CI laufen und legt das Release mit generierten Notes an.

Eine Claude-Session kann den Workflow nicht starten: ihr Token darf Actions nur lesen, die API antwortet mit 403. Der Start bleibt deshalb beim Maintainer, im Browser oder mit seinem eigenen `gh` (nicht auf dem Host, der Projekt-Benutzer hat keinen Token):

```
gh workflow run release.yml --repo fellek/agent-pipeline --ref main -f tag=<tag> -f notes='<hinweise>'
```

## 3. Bump-PR öffnen

Automatisch: Der Timer sieht das neue Release und öffnet den PR `Bump pipeline to <tag>` in einem Wegwerf-Klon als `autopilot`. Er öffnet keinen, wenn der Pin schon auf dem Release steht oder ein geschlossener Bump-PR auf dieses Release existiert.

Von Hand: dem Bot `update` senden (nur ohne laufendes Issue). Ein Rollback auf das vorige Release: `rollback`; den PR merged nur der Weg von Hand aus 6.

## 4. und 5. Ankündigung, Wartezeit, Veto

Der Timer schickt per Telegram, ab wann er das Update installiert. Die 12 Stunden laufen erst, wenn diese Nachricht gesendet ist.

- Abbrechen: den Bump-PR auf GitHub schließen. Der Timer lässt dieses Release dann aus, auch wenn später wieder ein Bump-PR darauf offen ist; das nächste Release nimmt er wieder.
- Nicht warten: weiter mit 6. von Hand.

## 6. bis 8. Approve, Merge, Gate, Claude Code

Automatisch nach den 12 Stunden. Von Hand alles in einem Befehl, als root; er zeigt die Release Notes und fragt:

```
/opt/pipeline/update-host autopilot
```

Gibt es `/opt/pipeline/update-host` noch nicht (erstes Update auf ein Release mit Timer), einmalig aus einem Wegwerf-Klon des Releases, als root:

```
git clone -q --branch <tag> https://github.com/fellek/agent-pipeline /tmp/pipeline && /tmp/pipeline/host/update-host.sh autopilot; rm -rf /tmp/pipeline
```

Die Teilschritte einzeln, wenn `update-host` selbst scheitert, als root:

1. Approve: `sudo -u pipeline-gate /opt/pipeline/gate review --manual autopilot <pr> <sha> approve`
2. Merge, sobald die CI grün ist: `sudo -u autopilot sudo -n -u pipeline-gate /opt/pipeline/gate merge <pr> <sha>`
3. Gate aus dem Release installieren, leere Eingabe behält den Token:

   ```
   git clone -q --branch <tag> https://github.com/fellek/agent-pipeline /tmp/pipeline
   /tmp/pipeline/host/install-gate.sh autopilot <owner>/<projekt> </dev/null
   ```

4. Claude Code in der Version aus `/tmp/pipeline/host/versions.sh`, dann den Klon löschen:

   ```
   v=$(. /tmp/pipeline/host/versions.sh && echo "$claude_code")
   sudo -u pipeline-gate -H bash -c 'cd && ~/.local/bin/claude install "$1"' _ "$v"
   sudo -u autopilot -H bash -c 'cd && ~/.local/bin/claude install "$1"' _ "$v"
   rm -rf /tmp/pipeline
   ```

Das Telegram-Plugin zieht kein Weg nach. Verlangt das Release eine andere Version, meldet `autopilot-start.sh` das per Telegram; dann als `autopilot` in `claude` `/plugin install telegram@claude-plugins-official`.

## 9. Autopilot neu starten

Automatisch: Im Leerlauf meldet der Poller den neuen Pin binnen einer Minute, sonst sieht der Autopilot ihn vor dem nächsten Issue; er holt das Release und startet darauf neu.

Von Hand: dem Bot `update` senden. Läuft der Dienst nicht, als `autopilot` im Projektverzeichnis das Release holen und den Dienst starten:

```
git pull
.claude/skills/pipeline/host/use-release.sh
XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user restart autopilot-<Repository>
```

`use-release.sh` nur in diesem Repository; in einem Projekt zieht `git pull` das Submodul mit.

## Timer

- Zustand: `systemctl list-timers 'pipeline-update@*'`, letzter Lauf: `journalctl -u pipeline-update@autopilot`.
- Sofort laufen lassen: `systemctl start pipeline-update@autopilot.service`.
- Ausschalten: `systemctl disable --now pipeline-update@autopilot.timer`; Updates dann nur von Hand. `install-gate.sh` schaltet ihn bei der nächsten Installation wieder ein.

Ohne Wartezeit hätte, wer das GitHub-Konto der Pipeline übernimmt, sofort root auf dem Host; mit ihr hat der Maintainer 12 Stunden für ein Veto. 2FA auf GitHub ist Pflicht.
