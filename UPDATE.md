# Release und Update

Wie eine neue Version der Pipeline entsteht und auf einen Host kommt: erst der automatische Weg, dann zu jedem Schritt der Weg von Hand. Einrichtung: [INSTALL.md](INSTALL.md).

Wie in INSTALL.md heißt der Projekt-Benutzer `autopilot`, sein Dienst `autopilot-<Repository>`. Platzhalter: `<tag>` ist das Release (etwa `v0.3.3`), `<pr>` die Nummer des Bump-PRs, `<sha>` sein Head-Commit. "root" heißt eine root-Shell auf dem Host, sonst `sudo` davor.

## Ablauf

| # | Schritt | Automatisch | Wer von Hand |
|---|---|---|---|
| 1 | Version erhöhen | nein | Telegram `release`, PR |
| 2 | Release anlegen | Workflow `release` nach dem Start | root `gate release`, Browser |
| 3 | Bump-PR öffnen | Timer `pipeline-update@autopilot` | Telegram `update` |
| 4 | Ankündigung | Timer, per Telegram | entfällt |
| 5 | 12 Stunden warten, Veto möglich | Timer | Bump-PR schließen |
| 6 | Approve und Merge | Timer | root |
| 7 | Gate installieren | Timer | root |
| 8 | Claude Code nachziehen | Timer | root |
| 9 | Autopilot neu starten | Autopilot selbst | Telegram `update` |

Der Timer läuft als root alle 15 Minuten (`/opt/pipeline/update-host --auto autopilot`), eingerichtet von `install-gate.sh`. Er nimmt nur das neueste veröffentlichte stabile Release, dessen Tag auf `main` der Pipeline liegt, und nur einen Bump-PR, der allein den Pin auf diesen Tag setzt. Fehler meldet er einmal per Telegram; Details: `journalctl -u pipeline-update@autopilot`.

## 1. Version erhöhen

Dem Bot `release` senden (nur ohne laufendes Issue). Er antwortet mit der neuen Version je Stufe und den Buttons `release major`, `release minor` und `release patch`. Ein Druck öffnet den PR `Bump plugin to <version>` auf dem Branch `bump-plugin-<version>`, eine Stufe über dem neuesten Release, und antwortet mit dem Link und den root-Befehlen für Approve und Merge unten. Ist der PR schon offen, nennt er ihn erneut.

In einer Claude-Code-Session in einem Klon dieses Repositorys tut der Skill `/release` dasselbe, mit einer Rückfrage statt Buttons. Er braucht `git` und `gh` mit Schreibrecht auf das Repository, in einer Cloud-Session ohne `gh` geht er also nicht. Die root-Befehle nennen den Benutzer, unter dem er läuft; außerhalb des Hosts dort `<benutzer>` einsetzen. Den Workflow startet auch er nie selbst.

Ein PR, der `version` in [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json) erhöht, durch Gate-Review und Merge wie jeder PR dieses Repositorys. Das Gate wählt das Repository nach dem aufrufenden Benutzer, deshalb hier nicht `autopilot`, sondern `<benutzer>`: der Benutzer, dessen Gate dieses Repository hält (der Autopilot der Pipeline selbst). Von Hand auf dessen Host als root, nachdem die CI des PRs grün ist:

```
sudo -u <benutzer> sudo -n -u pipeline-gate /opt/pipeline/gate review <pr> <sha>
sudo -u <benutzer> sudo -n -u pipeline-gate /opt/pipeline/gate merge <pr> <sha>
```

Statt des Reviews durch das Gate geht auch das Verdict des Maintainers: `sudo -u pipeline-gate /opt/pipeline/gate review --manual <benutzer> <pr> <sha> approve`.

## 2. Release anlegen

Nach dem Merge aus 1. dieselbe Stufe erneut senden, also etwa wieder `release patch` (oder `/release`). Statt eines neuen PRs kommt der root-Befehl, der den Workflow startet:

```
sudo -u pipeline-gate /opt/pipeline/gate release <benutzer> <tag> <sha> "$(cat <hinweise>.md)"
```

Das letzte Argument sind die Update-Hinweise (`notes`), ohne Hinweise weglassen. Das Gate startet den Workflow nur für root, nur wenn `<sha>` der Head von `main` ist, `<tag>` `v` plus die Version in dessen `plugin.json` und es dieses Release noch nicht gibt; der Workflow bricht ab, wenn `main` sich bis zu seinem Start bewegt hat. Die Session selbst kann kein Release starten, denn der Timer installiert jedes auf allen Hosts. Dafür braucht der Token des Gates für dieses Repository Actions mit Lesen und Schreiben ([INSTALL.md](INSTALL.md), Schritt 2.1); ohne antwortet GitHub mit 403 "Resource not accessible by personal access token".

Ohne Gate im Browser: Actions, Workflow `release`, "Run workflow" auf `main`. `tag` ist `v` plus die Version aus 1., `notes` die Update-Hinweise (was ein Projekt von Hand anpassen muss), leer lassen, wenn es keine gibt. Der Workflow lässt die CI laufen und legt das Release mit generierten Notes an.

Oder mit dem eigenen `gh` des Maintainers (nicht auf dem Host, der Projekt-Benutzer hat keinen Token):

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

Gibt es `/opt/pipeline/update-host` noch nicht (erstes Update auf ein Release mit Timer), einmalig vorher als root das Gate aus einem Wegwerf-Klon des Releases installieren; das legt `update-host` und den Timer an. `mktemp -d`, nicht ein fester Pfad in `/tmp`: den könnte der Projekt-Benutzer vorher anlegen und die Dateien tauschen, die root dann installiert.

```
d=$(mktemp -d)
git clone -q --branch <tag> https://github.com/fellek/agent-pipeline "$d/pipeline"
"$d/pipeline/host/install-gate.sh" autopilot <owner>/<projekt> </dev/null
rm -rf "$d"
/opt/pipeline/update-host autopilot
```

Die Teilschritte einzeln, wenn `update-host` selbst scheitert, als root:

1. Approve: `sudo -u pipeline-gate /opt/pipeline/gate review --manual autopilot <pr> <sha> approve`
2. Merge, sobald die CI grün ist: `sudo -u autopilot sudo -n -u pipeline-gate /opt/pipeline/gate merge <pr> <sha>`
3. Gate aus dem Release installieren, leere Eingabe behält den Token:

   ```
   d=$(mktemp -d)
   git clone -q --branch <tag> https://github.com/fellek/agent-pipeline "$d/pipeline"
   "$d/pipeline/host/install-gate.sh" autopilot <owner>/<projekt> </dev/null
   ```

4. Claude Code in der Version aus `host/versions.sh` des Releases, dann den Klon löschen:

   ```
   v=$(. "$d/pipeline/host/versions.sh" && echo "$claude_code")
   sudo -u pipeline-gate -H bash -c 'cd && ~/.local/bin/claude install "$1"' _ "$v"
   sudo -u autopilot -H bash -c 'cd && ~/.local/bin/claude install "$1"' _ "$v"
   rm -rf "$d"
   ```

Das Telegram-Plugin zieht kein Weg nach. Verlangt das Release eine andere Version, meldet `autopilot-start.sh` das per Telegram; dann als `autopilot` in `claude` `/plugin install telegram@claude-plugins-official`.

## 9. Autopilot neu starten

Automatisch: Im Leerlauf meldet der Poller den neuen Pin binnen einer Minute, sonst sieht der Autopilot ihn vor dem nächsten Issue; er holt das Release und startet darauf neu.

Von Hand: dem Bot `update` senden. Läuft der Dienst nicht, als `autopilot` im Projektverzeichnis das Release holen und den Dienst starten:

```
git pull
host/use-release.sh
XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user restart autopilot-<Repository>
```

`use-release.sh` nur in diesem Repository; in einem Projekt zieht `git pull` das Submodul mit.

## Timer

- Zustand: `systemctl list-timers 'pipeline-update@*'`, letzter Lauf: `journalctl -u pipeline-update@autopilot`.
- Sofort laufen lassen: `systemctl start pipeline-update@autopilot.service`.
- Ausschalten: `systemctl disable --now pipeline-update@autopilot.timer`; Updates dann nur von Hand. Jedes Update von Hand (6.) schaltet ihn über `install-gate.sh` wieder ein; dann danach erneut ausschalten.

Ohne Wartezeit hätte, wer das GitHub-Konto der Pipeline übernimmt, sofort root auf dem Host; mit ihr hat der Maintainer 12 Stunden für ein Veto. 2FA auf GitHub ist Pflicht.
