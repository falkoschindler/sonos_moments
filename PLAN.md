# Sonos Moments — Umbauplan

Ziel: Live-Updates statt Polling, spürbar schnellere UI, robuster Dauerbetrieb auf einem Raspberry Pi Zero 2 W. Der Umbau betrifft vor allem die Infrastruktur; Feature-Wünsche kommen separat dazu.

## Stand

Auf Branch `rebuild-event-driven` umgesetzt und gegen das laufende System verifiziert: Etappe 1 (Registry und State-Layer), Etappe 2 (Event-Subscriptions), Etappe 3 (Schreibpfad) und der Datenmodell-Teil von Etappe 4 (Quellen-Referenzen, Favoriten-Menü). Offen sind der UI-Neubau, die TuneIn-Suche, Watchdog und Deployment sowie optional SoundCloud und Mixcloud.

Zwei Erkenntnisse aus der Umsetzung, die vorher nicht auf dem Schirm waren:

**Die Favoriten mit `sid=333` sind tot.** Alle Favoriten des alten TuneIn-(New)-Dienstes mit `sn=8` — 1LIVE, FluxFM, WDR 2/3/5, SomaFM und die übrigen — werden von den Speakern mit `UPnP Error 402 Invalid Args` abgelehnt. Der Dienst ist offenbar nicht mehr mit dem Haushalt verknüpft. Was funktioniert, sind die Favoriten mit `sid=303` (Sonos Radio, `sn=5`), etwa radioeins, House FM und Klassik Radio Piano. Das ist vermutlich derselbe Vorgang, der die alten Moments zerstört hat. Die betroffenen Favoriten müssten in der Sonos-App einmal neu angelegt werden; die App sagt jetzt wenigstens deutlich, dass es an der Verknüpfung liegt.

**Nach dem Setzen einer neuen Stream-Quelle braucht der Speaker einen Moment.** Ein sofortiges `play()` scheitert an `UPnP Error 701 Transition not available`, mit etwa einer Sekunde Abstand klappt es. Deshalb sind Quelle setzen und Abspielen getrennt, mit Wiederholung.

## Ausgangslage

Gemessen am Live-System (4 Speaker, Sonos 86.8-78270, S1/Play:1 u.a.):

- SSDP-Antwortzeiten der Speaker: 84 / 156 / 358 / 390 ms. Im Fehlerfall (verlorenes Multicast über WLAN) wartet `soco.discover()` den Default-Timeout ab.
- Ein SOAP-Roundtrip (`GetVolume`, Port 1400) dauert 9–11 ms vom Mac aus. Auf dem Zero 2 W über WLAN eher 30–80 ms, inklusive XML-Parsing in Python.
- Die lokale Control-API auf Port 1443 ist auf den Geräten aktiv (`allowGuestAccess: true`, `credentialTypeAllowed: API_KEY`, `apiVersion: 1.53.1`), lehnt aber jeden Request mit `Origin`-Header mit 403 ab. Für Browser-Clients also unbrauchbar, für einen Python-Prozess grundsätzlich nutzbar — wir bleiben aber bei SoCo/UPnP, weil nur dort Events, Queue-Handling und Snapshot-Logik ausgereift sind.

Die drei Bremsen im aktuellen Code sind nicht NiceGUI, sondern blockierendes I/O im Render-Pfad:

1. `app.py:25` ruft `system.update_devices()` (= `soco.discover()`) synchron bei jedem Seitenaufruf auf und blockiert damit den Event-Loop für alle Clients.
2. `speakers_ui` liest pro Gerät `volume`, `mute`, `is_coordinator`, `group.uid` — jeder Zugriff ein eigener synchroner Netzwerk-Roundtrip, serialisiert.
3. `speakers.py:44` wartet nach jeder Gruppenänderung fest `asyncio.sleep(1.0)` und macht danach eine zweite Discovery. `Moment.capture()` in `moment.py:20` macht eine dritte.

Nebenbefunde: `main.py` ruft `main()` ohne Argument, also mit `reload=True` — auf dem Pi läuft dann watchfiles mit. Und Umbenennen eines Moments in `moments_ui` persistiert nicht, weil `_save()` nicht aufgerufen wird.

## Ziel-Architektur

### 1. Geräte-Registry statt Discovery im Render-Pfad

Das Problem ist nicht Discovery an sich, sondern Discovery bei jedem Seitenaufruf. Die Lösung ist eine persistente Registry, die Geräte über ihre **UID** führt (`RINCON_B8E937EE4EA001400` — darin steckt die MAC-Adresse, also stabil über Router- und DHCP-Wechsel hinweg) und die zuletzt bekannte IP nur als Cache hält.

Ablauf beim Start: alle bekannten IPs parallel anpingen und die UID gegenprüfen. Das kostet pro Gerät einen Roundtrip von ~10 ms, läuft nebenläufig und ist damit faktisch instantan. Entscheidend ist der Selbstheilungs-Mechanismus: **Sobald ein einziger Speaker unter bekannter IP antwortet, liefert `device.all_zones` den kompletten Haushalt inklusive aller aktuellen IPs.** Nach einem Router-Wechsel, bei dem sich die Adressen verschieben, genügt also ein Treffer, um den Rest zu reparieren.

Erst wenn gar nichts antwortet — oder auf Knopfdruck in der UI — läuft eine echte Suche, und zwar im Hintergrund und nie im Render-Pfad:

1. `soco.discovery.discover()` per SSDP. Schnell, wenn Multicast durchkommt (die Speaker antworteten hier in 84–390 ms).
2. Falls das leer bleibt: `soco.discovery.scan_network()`. Das scannt das lokale Subnetz per TCP und ist laut Docstring genau für den Fall gedacht, dass Multicast nicht funktioniert — also für unser WLAN-Szenario auf dem Pi. Parameter: `max_threads` (Default 256, auf dem Zero 2 W eher 32–64 ansetzen), `scan_timeout=0.5`, `min_netmask=24`.

Damit ist „Geräte suchen" ein normales Feature in der App statt einer Voraussetzung für den Start, und feste IPs sind nur noch der Notnagel, den man nicht braucht. Aktuell im Netz: 192.168.0.46, 192.168.0.101 („Living Room"), 192.168.0.141, 192.168.0.154.

### 2. Langlebiger State im Speicher

Ein prozessweiter `SonosSystem` hält den kompletten Zustand als reine Python-Datenstruktur: pro Player Name, UID, Volume, Mute, pro Gruppe Koordinator, Mitglieder, Transport-State und aktueller Track. Die UI liest **ausschließlich** aus diesem Speicherabbild und macht beim Rendern null Netzwerk-Calls. Ein Seitenaufruf ist damit unabhängig von Netz und Speakern und praktisch instantan — das ist der größte einzelne Gewinn für das Gefühl der App.

### 3. Event-Subscriptions

Statt zu pollen, abonnieren wir UPnP-Events. Relevante Services:

| Service | Wo | Liefert |
|---|---|---|
| `RenderingControl` | jeder Player | Volume, Mute (Kanal `Master`), später Bass/Treble/Loudness |
| `AVTransport` | pro Koordinator | Transport-State, aktueller Track, Position, Queue-Wechsel |
| `ZoneGroupTopology` | ein Player genügt | Gruppierung des ganzen Household |
| `GroupRenderingControl` | pro Koordinator | Gruppenlautstärke (für das geplante Multi-Speaker-Volume) |

Technisch: `sub = device.renderingControl.subscribe(requested_timeout=600, auto_renew=True)`. SoCo startet dabei einen HTTP-Listener in einem Hintergrund-Thread, an den die Speaker `NOTIFY`-Requests schicken; Default-Port ist `config.EVENT_LISTENER_PORT = 1400`, bei Belegung weicht SoCo nach oben aus. Auf dem Pi ist 1400 frei (das ist der Port *der Speaker*, nicht unserer). Wenn der Pi mehrere Interfaces hat, muss `config.EVENT_ADVERTISE_IP` gesetzt werden, sonst bewerben wir womöglich die falsche Adresse und es kommen nie Events an.

Wichtig: Ein `ZoneGroupTopology`-Event bedeutet, dass sich Koordinatoren geändert haben können. Der Subscription-Manager muss darauf reagieren und die `AVTransport`-Abos entsprechend umhängen. Das ist die einzige echte Zustandslogik im Event-Handling und gehört an genau eine Stelle.

### 4. Brücke Thread → asyncio → UI

Events landen in `sub.events`, einer `queue.Queue`, gefüllt aus einem Fremd-Thread. Sauberster pragmatischer Weg in NiceGUI: ein `ui.timer(0.1, drain)` auf App-Ebene, der alle Queues mit `get_nowait()` leerräumt, den State aktualisiert und bei Änderungen die betroffenen Refreshables aktualisiert. 100 ms Granularität ist nicht wahrnehmbar und wir umgehen jede Thread-Safety-Diskussion mit dem Event-Loop. Alternative wäre ein Reader-Thread mit `loop.call_soon_threadsafe` — mehr Kontrolle, mehr Fehlerquellen; erst nehmen, wenn die 100 ms je störten.

Die UI-Aktualisierung sollte feingranular werden: nicht das gesamte `speakers_ui` neu bauen, wenn sich ein Volume ändert, sondern gezielt binden (`bind_value_from` auf das State-Objekt). Sonst flackert bei jedem Event die ganze Seite und offene Menüs schließen sich.

### 5. Schreibpfad

Alle schreibenden SoCo-Aufrufe laufen über `asyncio.to_thread`, damit der Event-Loop nie blockiert. Die UI wartet **nicht** auf eine Bestätigung und macht auch keinen Refresh — die Bestätigung kommt als Event zurück. Damit verschwindet der `asyncio.sleep(1.0)`-Hack ersatzlos.

Neu zu lösen ist die Echo-Problematik: Während man am Knob dreht, feuert der Speaker Events mit Zwischenwerten, die den Regler zurückspringen lassen. Lösung: pro Gerät ein „pending write" mit Zielwert und Zeitstempel; eingehende Volume-Events für dieses Gerät werden ignoriert, bis entweder der Zielwert bestätigt ist oder ~500 ms vergangen sind. Zusätzlich die Knob-Writes drosseln (höchstens ein SOAP-Call pro ~100 ms, letzter Wert gewinnt).

### 6. Robustheit

Ein Watchdog-Timer (z. B. alle 60 s) prüft, ob alle Subscriptions noch leben, und baut sie sonst neu auf. Nötig, weil Speaker rebooten, Firmware-Updates einspielen und WLAN wegbricht. Zusätzlich ein „stale"-Kennzeichen im State: wenn ein Player länger als X Minuten kein Event geschickt und auch nicht auf einen Ping geantwortet hat, wird er in der UI ausgegraut statt mit veralteten Werten angezeigt. Beim Prozessende alle Subscriptions explizit `unsubscribe()` — sonst schicken die Speaker noch minutenlang NOTIFYs ins Leere.

Geräte fliegen dabei **nicht** automatisch aus der Registry, sondern bleiben ausgegraut stehen: Ein Speaker an einer abgeschalteten Steckdose ist der Normalfall, kein Fehler. Aufräumen passiert nur von Hand. Der Watchdog nimmt einen ausgegrauten Player periodisch wieder in den Verbindungsversuch auf, damit er nach dem Einschalten von allein zurückkommt.

### 7. Moments neu aufsetzen

Weil der State ohnehin live im Speicher liegt, wird `capture()` zu einem reinen Dict-Copy: keine Discovery, keine SOAP-Calls, unmittelbar. Das ist der zweite große Gewinn.

Wichtiger ist aber, **was** ein Moment speichert. Aktuell ist es `get_current_track_info()['uri']`, und genau daher kommt das Problem, dass Moments nach einiger Zeit nicht mehr funktionieren. Ein Vergleich zweier Speaker im laufenden System, beide auf radioeins:

```
Bathroom: x-sonosapi-stream:tunein%3a9575?sid=303&flags=8224&sn=5
Bedroom:  x-rincon-mp3radio://http://f131.rndfnk.com/ard/rbb/radioeins/live/mp3/128/stream.mp3
          ?aggregator=tunein&cid=…&sid=…&token=3Kzgz7VwsReWjF7AssUfU6gCbfv29CIFh3FrunUeQIk&tvf=…
```

Die erste ist eine stabile Dienst-Referenz, die zweite eine bereits aufgelöste CDN-URL mit Ablauf-Token und fester Edge-Node. Speichert man die zweite in einem Moment, ist sie nach Ablauf des Tokens wertlos. Dazu kommt ein zweiter Verfallsmechanismus: `sn=` ist die Seriennummer des verknüpften Dienst-Accounts. Wird ein Dienst neu verknüpft oder von Sonos migriert, ändert sie sich und alle gespeicherten URIs brechen. In den Favoriten sind beide Generationen sichtbar — ältere Einträge auf `sid=333&sn=8` (TuneIn (New)), neuere auf `sid=303&sn=5` (Sonos Radio). Das ist mit ziemlicher Sicherheit der Grund, warum Moments neu aufgenommen werden mussten.

Konsequenz: Ein Moment speichert pro Gruppe nicht die Transport-URI, sondern eine **Quellen-Referenz** als getaggte Union:

| Typ | Inhalt | Robustheit |
|---|---|---|
| `favorite` | Titel + Item-ID des Sonos-Favoriten | am höchsten — Sonos pflegt die Favoriten selbst über Account-Wechsel hinweg |
| `service_item` | Service-ID, Item-ID, Servicename | hoch, solange der Dienst verknüpft bleibt |
| `queue` | Queue-Inhalt bzw. Container-URI, Tracknummer, Position | für Playlists und Alben |
| `none` | nichts | Moment setzt nur Gruppierung und Lautstärken |

Aufgelöst wird erst beim Abspielen. Lässt sich eine Quelle nicht mehr auflösen, wird der Moment in der UI als reparaturbedürftig markiert und man kann die Quelle neu auswählen, statt dass stumm nichts passiert.

Ein Moment ist ausdrücklich eine **Aktion**, kein Zustand: Er wird abgefeuert und danach nicht weiter beobachtet. Es gibt keinen Abgleich zwischen aktueller Situation und gespeicherten Moments und damit auch keinen „aktiven" Moment — das erspart uns die unangenehme Frage, wie ähnlich zwei Lautstärke-Sätze sein müssen, um als derselbe Moment zu gelten.

Beim Abspielen wird trotzdem verglichen, allerdings nur einmalig und nur, um Arbeit zu sparen: Statt die Gruppierung stumpf abzureißen und neu aufzubauen, berechnet eine reine Funktion `plan(moment, state, favorites)` die Differenz zwischen Soll und Ist und gibt nur die aus, was sich tatsächlich ändern muss. Drei Regeln machen das allgemein tragfähig:

- **Wer koordiniert, ist egal.** Stimmt die Mitgliedermenge einer Gruppe, wird sie akzeptiert, auch wenn ein anderer Speaker die Rolle des Koordinators hat. Das ist für den Nutzer unsichtbar und würde sonst ständig unnötige Neuaufbauten auslösen. Die Quelle geht dann an den aktuellen Koordinator.
- **Nur überspringen, wenn Gleichheit bewiesen ist.** Eine bereits aufgelöste Stream-URL lässt sich nicht gegen einen Favoriten matchen; in dem Fall wird die Quelle neu gesetzt. Im Zweifel handeln, nicht raten — schlimmstenfalls landet man beim alten Verhalten.
- **Ein Moment fasst nur an, was er nennt.** Nicht genannte Speaker bleiben unberührt. Einzige unvermeidbare Ausnahme: Wer mit einem genannten Speaker in einer Gruppe hängt und dort nicht hingehört, muss sie verlassen.

Weil der Abgleich nur so gut ist wie das Bild, das ihm zugrunde liegt, läuft vorher ein Refresh. Und weil die Funktion rein ist, ist sie ohne Speaker testbar — siehe `tests/test_plan.py`.

Beim Restore hat der aktuelle Ansatz zusätzlich einen echten Fehler: `play_uri(group.uri)` ersetzt die Queue durch einen einzelnen Track. Wer aus einer Playlist hörte, verliert sie. Richtig ist der Weg, den `soco.snapshot.Snapshot` intern geht — Wiedergabe relativ zur Queue über `x-rincon-queue:<UID>#0` plus Tracknummer und Position, mit Sonderfall für Radio-Streams. `Snapshot` selbst ist nicht serialisierbar und taugt daher nicht für persistierte Moments, aber die Logik übernehmen wir.

Ebenfalls zu korrigieren ist die Reihenfolge beim Restore: erst die komplette Topologie herstellen (alle `unjoin`/`join`), dann Volumes und Mute setzen, dann Transport starten. Aktuell startet der Koordinator die Wiedergabe, bevor die Mitglieder beigetreten sind.

Das Speicherformat ändert sich damit inkompatibel. Bei der Handvoll bestehender Moments ist Neu-Aufnehmen billiger als eine Migration — beim Laden einfach alte Einträge verwerfen und eine Notiz in der UI zeigen.

## Quellen auswählen statt in der Sonos-App suchen

Ziel ist, dass ein Moment in Sonos Moments **zusammengestellt** und nicht nur mitgeschnitten wird: Speaker auswählen, Lautstärken setzen, Quelle aussuchen — fertig, ohne Umweg über die offizielle App. Was dafür geht, habe ich am laufenden System durchprobiert:

**Sonos-Favoriten funktionieren sofort und ohne jede Authentifizierung.** `music_library.get_sonos_favorites()` liefert aktuell 23 Einträge, überwiegend Radiosender (WDR 2/3/5, 1LIVE, FluxFM, Bremen Zwei, radioeins, SomaFM, Klassik Radio Piano, House FM …) plus eine SoundCloud-Playlist. Da die Quellen ohnehin schon dort gepflegt sind, deckt ein simpler Favoriten-Browser den Alltag vermutlich fast vollständig ab. Drei Einträge sind Sonos-Werbe-Kacheln ohne abspielbare Resource („Discover Sonos Radio", „Sonos Presents", „Trending Now") — die müssen beim Auflisten weggefiltert werden.

**TuneIn-Suche funktioniert ebenfalls sofort und ohne Auth.** Der klassische TuneIn-Dienst (`sid=254`) hat den Auth-Typ `Anonymous`. Getestet:

```python
MusicService('TuneIn').search(category='stations', term='radioeins')
# -> MSStream 'radioeins' (s25111), 'radioeins Cottbus' (s309554), 'Radio EINS' (s119567), …
```

Suchkategorien sind `stations`, `shows`, `hosts`. Damit lässt sich das Stöbern und Suchen nach Radiosendern vollständig in der App abbilden. Zu verifizieren ist beim Umsetzen noch das Abspielen: `sonos_uri_from_id()` liefert eine `soco://`-Pseudo-URI, und Dienst-Items brauchen beim `play_uri` die passenden DIDL-Metadaten inklusive Service-Descriptor. Das ist der fummelige Teil.

**SoundCloud und Mixcloud brauchen eine eigene Anmeldung in unserer App.** Beide antworten momentan mit Auth-Fehlern:

```
SoundCloud (sid=160, AppLink):    'Authentication failed: OAuth token expired or invalid'
Mixcloud   (sid=181, DeviceLink): 'Authorization for Mixcloud expired, is invalid or has not yet been completed'
```

SoCo unterstützt das über `begin_authentication()` / `complete_authentication(link_code, link_device_id)` mit einem eigenen Token-Store, den wir persistieren müssten — der Nutzer bekommt eine URL und einen Code angezeigt und bestätigt die Verknüpfung im Browser. Machbar, aber ein eigenes Arbeitspaket inklusive Token-Refresh und Fehlerbehandlung. Suchkategorien wären SoundCloud `artists/albums/tracks/playlists` und Mixcloud `tags/Shows/Users`.

**Abhängigkeit:** Der Token-Store und die aktuelle `MusicService`-API gibt es erst ab SoCo 0.31; das Projekt pinnt derzeit `soco = "^0.30.4"`. Für den Feature-Teil also auf 0.31.x hochziehen.

Vorgeschlagene Reihenfolge: Favoriten-Browser zuerst (billig, robust, deckt den Alltag), dann TuneIn-Suche (ebenfalls ohne Auth), SoundCloud und Mixcloud zuletzt und nur, wenn der Bedarf bleibt.

## UI neu denken

Die bestehende UI hat drei Annahmen eingebaut, die der Umbau kippt, und das ist der eigentliche Grund, sie neu zu denken.

**Erstens sind Moments heute ein Anhängsel.** Oben die Speaker-Tabs mit allen Reglern, unten eine schmale Zwei-Spalten-Liste mit den Moments. Ein Moment ist eine reine Aktion — antippen, fertig — und gehört damit prominent und gut mit dem Daumen erreichbar platziert, aber nicht flächig: Buttons, keine Kachelwand. Kein zweiter Bereich, keine Navigation. Alles liegt auf einem Screen.

**Zweitens bilden die Tabs die Gruppentopologie ab, die sich ab jetzt live unter der UI verändert.** Schon heute muss `speakers.py` am Ende abfangen, dass `tabs.value` ins Leere zeigt; mit Events passiert das ständig, weil sich Gruppen-Keys und Koordinatoren ändern, sobald jemand anders etwas umgruppiert. Tabs, deren Identität und Anzahl sich unter der Hand ändern, sind dafür die falsche Struktur. Besser ist eine durchgehende Liste aller Räume, in der Gruppenzugehörigkeit visuell dargestellt wird (Einrückung, Klammer, gemeinsame Kopfzeile) statt über die Navigation. Nebeneffekt: Man sieht alle Räume gleichzeitig, was beim Umgruppieren ohnehin hilft.

**Drittens zeigt die UI nicht, was läuft.** Es gibt Play/Pause/Stop, aber weder Sender noch Titel. Mit `AVTransport`-Events fällt beides praktisch gratis an und ist genau die Information, für die man sonst die offizielle App aufmacht. „Küche: radioeins" pro Gruppe ist wahrscheinlich der größte wahrgenommene Qualitätssprung im ganzen Umbau.

Dazu ein Moment-Editor, der aus dem Quellen-Feature folgt: Räume auswählen, Lautstärken setzen, Quelle aus Favoriten oder Suche wählen, speichern. Damit ersetzt „Moment anlegen" den Umweg über die Sonos-App, und „Re-capture" wird vom Hauptweg zur Abkürzung.

Kleinigkeiten fürs Handy: Der `ui.knob` ist am Desktop hübsch, mit dem Daumen aber fummelig — Slider mit großer Trefferfläche plus die vorhandenen +/−-Buttons sind dort die bessere Wahl. Und da die UI künftig live aktualisiert, muss das Rendern feingranular an den State gebunden sein, sonst schließen sich bei jedem eingehenden Event offene Menüs und Dialoge.

**Entschieden:** Es gibt keine getrennte Raum-Ansicht. Der Screen zeigt dauerhaft, was gerade wo läuft — pro Gruppe eine Zeile mit Raumnamen, Sender oder Titel, Transport-Zustand und Lautstärke — und darüber oder darunter die Moments als Aktionsleiste. Die Statusanzeige ist damit auch die Rückmeldung: Nach dem Antippen eines Moments sieht man unmittelbar, dass sich Gruppierung, Quelle und Lautstärken geändert haben. Genau deshalb braucht es keine Hervorhebung eines „aktiven" Moments — und der Modellteil, der die aktuelle Situation mit gespeicherten Moments abgleichen müsste, entfällt ersatzlos.

## Deployment auf dem Zero 2 W

Der Zero 2 W (4× Cortex-A53, 1 GHz, 512 MB) reicht für diese Last problemlos: Python mit FastAPI und socketio liegt bei grob 60–100 MB, das Quasar-Bundle parst das Handy und nicht der Pi, und pro Interaktion fällt praktisch nur eine Websocket-Nachricht an. Wenn sich der Pi überfordert anfühlt, sind das nach meiner Erfahrung mit hoher Wahrscheinlichkeit diese Punkte:

- **WLAN-Powersave.** Standardmäßig an, verursacht regelmäßig 100–300 ms Latenzspitzen und ist die häufigste Ursache für „reagiert träge". Abschalten: `iw dev wlan0 set power_save off`, dauerhaft per systemd-Unit oder NetworkManager-Setting.
- **Unterspannung.** `vcgencmd get_throttled` und `dmesg | grep -i voltage` prüfen. Ein schwaches Netzteil oder ein dünnes Micro-USB-Kabel drosseln den Takt dauerhaft, das fühlt sich exakt wie „zu langsame Hardware" an.
- **Reload-Modus.** Sicherstellen, dass der Dienst über den `sonos-moments`-Entrypoint (`main_without_reload`) startet und nicht über `python main.py`.
- **Startart.** systemd-Unit mit `Restart=always` und `After=network-online.target`, Logs nach journald mit Rate-Limit, damit die SD-Karte nicht vollgeschrieben wird.
- **SD-Karte.** Billige Karten mit schlechten Random-Writes bremsen jeden Neustart und jedes Log. Mit `hdparm -t` bzw. `dd` gegenprüfen.

Dazu die PWA-Kosmetik, damit das Ganze sich auf dem Handy wie eine App anfühlt: eine Route für `manifest.json`, `ui.add_head_html` mit `<link rel="manifest">`, `apple-mobile-web-app-capable` und `apple-mobile-web-app-status-bar-style`, plus Icons. Über iOS-Safari genügt das für „Zum Home-Bildschirm" inklusive Vollbild, auch ohne HTTPS. Offline-Fähigkeit gibt es nicht und braucht es nicht, weil die App ohne Heimnetz sowieso nichts steuern kann.

## Rewrite oder schrittweise?

Die Frage entschärft sich an der Größe: Das Projekt sind 292 Zeilen. Inhaltlich ist es trotzdem ein Rewrite, denn von den bestehenden Bausteinen überlebt fast nichts — `System` wird von der Polling- zur Event-Klasse, `Moment` bekommt ein anderes Datenmodell, `Device` und `Group` verlieren ihre Doppelrolle, und die UI wird ohnehin neu gedacht. Erhalten bleiben `app.py` als Gerüst, die Persistenz über `app.storage.general` und die gesammelte Erfahrung, welche Quasar-Elemente sich gut anfühlen.

Der entscheidende Grund für einen Neuanfang am Modell ist eine Trennung, die heute fehlt: **Live-State** — was die Speaker gerade tun, aus Events gespeist, flüchtig — gegenüber **Moment** — ein gewünschter Zustand, persistiert, über Quellen-Referenzen beschrieben. Aktuell ist `Moment` beides in einem, Snapshot-Format und Wiederherstellungsanweisung, und `System` vermischt Live-Geräte mit gespeicherten Moments. Diese Trennung nachträglich in die bestehenden Dataclasses zu operieren wäre mehr Arbeit als sie neu zu schreiben.

Trotzdem nicht als Big Bang: Der Umbau läuft in der Reihenfolge unten, und nach jeder Etappe ist die App lauffähig. Bei dieser Codegröße kostet das kaum etwas und erspart die klassische Rewrite-Falle, wochenlang nichts Startbares zu haben. Praktisch heißt das: neues Modell neben dem alten aufbauen, UI umhängen, Altes löschen — nicht in einem Zug alles ersetzen.

Der UI-Neubau gehört zeitlich zu Etappe 4: Erst dann steht das Datenmodell, das die neue Oberfläche darstellen soll, und man baut nicht zweimal.

## Umsetzungsreihenfolge

1. ~~**State-Layer und Registry.**~~ *(erledigt)* Geräte-Registry über UIDs mit IP-Cache und Hintergrund-Suche, prozessweiter State, UI rendert ohne Netzwerk-Calls, alle SoCo-Aufrufe in `to_thread`.
2. ~~**Event-Subscriptions.**~~ *(erledigt)* Abos für RenderingControl, AVTransport und ZoneGroupTopology, Queue-Drain per Timer, Umhängen bei Topologie-Änderungen, Bindings statt Full-Refresh.
3. ~~**Schreibpfad.**~~ *(erledigt)* Echo-Suppression, Drosselung, `sleep(1.0)`-Hack entfernt.
4. **Moments und Quellen.** Quellen-Referenz statt Transport-URI, Favoriten-Menü und korrekte Restore-Reihenfolge sind erledigt. Offen: der Moment-Editor, queue-erhaltendes Capture für Playlists und der UI-Neubau.
5. **TuneIn-Suche.** Stöbern und Suchen nach Radiosendern direkt in der App.
6. **Watchdog und Deployment.** Stale-Kennzeichnung, systemd-Unit, Powersave, PWA-Manifest. Die Resubscribe-Logik steckt bereits im Sync der Subscriptions.
7. **Optional: SoundCloud und Mixcloud.** Auth-Flow mit Token-Store.

Etappen 1 bis 3 hängen inhaltlich zusammen und ergeben zusammen den eigentlichen Umbau; danach ist Etappe 4 der Teil mit dem größten Alltagsnutzen.

## Offene Punkte

- Weitere Feature-Wünsche sammeln (Roadmap im README nennt bereits Gruppenlautstärke, Alarme, Timer, Medienlinks).
- Mehrere gleichzeitige Clients: der State ist geteilt, damit sehen alle Geräte dasselbe. Pro Client bleiben nur UI-Details wie der ausgewählte Tab in `app.storage.user`.
- Authentifizierung: bislang keine. Solange nur im Heimnetz erreichbar, vermutlich in Ordnung — bewusst entscheiden statt implizit lassen.
