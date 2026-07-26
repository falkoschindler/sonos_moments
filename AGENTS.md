# Hinweise für Agents

Sonos-Controller auf Basis von NiceGUI und SoCo, läuft im selben Netz wie die Speaker. Der aktuelle Umbau und die nächsten Schritte stehen in [PLAN.md](PLAN.md) — dort zuerst nachsehen, bevor du etwas planst.

## Kommandos

```bash
uv run sonos-moments --port 8081   # starten (nicht python main.py, das schaltet den Reloader an)
uv run pytest                      # Tests, laufen ohne Speaker
uv run ruff check .                # Lint, läuft auch als pre-commit-Hook
```

Der Formatter (`ruff format`) ist bewusst **nicht** aktiv: Er würde den Stil des Projekts umwerfen. Anführungszeichen sind einfach, Zeilenlänge 120.

## Die Speaker sind echt

Es gibt keine Testumgebung. Jeder Schreibzugriff geht an vier Lautsprecher in einer bewohnten Wohnung, und Wiedergabe ist hörbar. Deshalb:

- Vor einem Test den Ist-Zustand aufnehmen (Gruppierung, Lautstärke, Mute, Quelle, Transport-Zustand) und danach exakt wiederherstellen.
- Zum Testen von Wiedergabe einen stummgeschalteten Speaker nehmen, nicht einen, der gerade läuft.
- Änderungen an der Gruppierung sind harmlos, solange nichts spielt — vorher prüfen.
- Lesende Aufrufe sind unbedenklich. Vieles lässt sich rein lesend verifizieren, etwa `plan()` gegen den Live-Zustand rechnen, ohne ihn anzuwenden.

Fällt dir keine unaufdringliche Testmöglichkeit ein, frag lieber nach, statt Musik anzuwerfen.

## Fallen, die Zeit gekostet haben

- Sobald ein `ZoneGroupTopology`-Abo besteht, hört SoCo auf, die Topologie zu pollen, und erwartet, dass der Abonnent den Cache füttert. Ohne das bleibt die Gruppierung für immer stehen. Siehe `System._read_topology`.
- In UPnP-Events sind Metadaten ein leerer String, wenn es nichts zu melden gibt. `getattr('', 'title', '')` liefert dann die Methode `str.title` statt des Defaults. Dafür gibt es `_text()`.
- Nach dem Setzen einer neuen Stream-Quelle braucht der Speaker rund eine Sekunde, bevor er `play()` annimmt, sonst `UPnP Error 701`.
- Ein Refresh erstreckt sich über mehrere `await`s. Nichts, was `state.groups` austauscht, darf dazwischenfunken — dafür gibt es das Lock in `System.refresh`.

## Konventionen

- Commit-Messages auf Englisch, Code und Kommentare ebenfalls; Dokumentation und Gespräch auf Deutsch.
- Kein Netzwerkzugriff im Render-Pfad. Die UI liest ausschließlich aus `SystemState`, alles Blockierende läuft in einem Thread.
- Logik, die man ohne Speaker testen kann, gehört in eine reine Funktion — Vorbild ist `plan()` mit `tests/test_plan.py`.
