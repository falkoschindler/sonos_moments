# Sonos Moments — rebuild plan

Goal: live updates instead of polling, a noticeably faster UI, robust continuous operation on a Raspberry Pi Zero 2 W. The rebuild is mostly about infrastructure; feature requests come on top of it, separately.

## Status

Implemented on branch `rebuild-event-driven`: stage 1 (registry and state layer), stage 2 (event subscriptions), stage 3 (write path), stage 4 (source references, favorites menu, reconciliation when playing, UI rebuild, moment editor, queue-preserving capture), stage 5 (browsing and searching TuneIn), and from stage 6 the stale marking. Independently of that came the move from Poetry to uv along with a modernization of the pre-commit hooks, a packaging fix that gets `icon.png` into the wheel in the first place, and — pulled forward from stage 6 — the PWA manifest.

For the TuneIn search, browsing, searching, playing a station that was found, and the selection dialog are verified in the browser. The stale marking as well: with an invented fifth speaker in the registry that never answers, which made it possible to check the greying out without cutting power to a real speaker.

Everything else is verified against the running system except restoring a queue: that would require something to be in a queue, and there is currently neither a local library (`list_library_shares()` is empty) nor a linked service from which something could be enqueued. That path is covered only by tests of the storage format.

**Next up**: the rebuild is substantively complete, including stage 6 — the board has been set up from scratch and runs with the read-only overlay. It continues with feature requests; the roadmap in the README lists group volume, alarms, timers and media links.

**Open details** nobody has decided yet:

- When a moment is pressed and there is nothing to do, nothing happens, and the app says so. The alternative would be forcing the stream to restart — one line, but a matter of taste.
- The moments the old card held are gone with it; they have to be recorded again.
- The favorites with `sid=333` would have to be recreated in the Sonos app, see below. Only whoever owns the Sonos household can do that.

Two findings from the implementation that were not on the radar beforehand:

**The favorites with `sid=333` are dead.** All favorites of the old TuneIn (New) service with `sn=8` — 1LIVE, FluxFM, WDR 2/3/5, SomaFM and the rest — are rejected by the speakers with `UPnP Error 402 Invalid Args`. The service is evidently no longer linked to the household. What does work are the favorites with `sid=303` (Sonos Radio, `sn=5`), such as radioeins, House FM and Klassik Radio Piano. This is presumably the same event that destroyed the old moments. The affected favorites would have to be recreated once in the Sonos app; the app at least now says clearly that the linkage is the cause.

**After setting a new stream source, the speaker needs a moment.** An immediate `play()` fails with `UPnP Error 701 Transition not available`; with about a second in between it works. That is why setting the source and starting playback are separate, with a retry.

## Starting point

Measured against the live system (4 speakers, Sonos 86.8-78270, S1/Play:1 among others):

- SSDP response times of the speakers: 84 / 156 / 358 / 390 ms. In the failure case (multicast lost over wifi), `soco.discover()` waits out the default timeout.
- A SOAP roundtrip (`GetVolume`, port 1400) takes 9–11 ms from a laptop. On the Zero 2 W over wifi more like 30–80 ms, including XML parsing in Python.
- The local control API on port 1443 is active on the devices (`allowGuestAccess: true`, `credentialTypeAllowed: API_KEY`, `apiVersion: 1.53.1`), but rejects every request carrying an `Origin` header with a 403. Unusable for browser clients, then, and usable in principle for a Python process — but we stay with SoCo/UPnP, because only there are events, queue handling and snapshot logic mature.

The three brakes in the current code are not NiceGUI but blocking I/O in the render path:

1. `app.py:25` calls `system.update_devices()` (= `soco.discover()`) synchronously on every page load and thereby blocks the event loop for all clients.
2. `speakers_ui` reads `volume`, `mute`, `is_coordinator`, `group.uid` per device — every access its own synchronous network roundtrip, serialized.
3. `speakers.py:44` waits a fixed `asyncio.sleep(1.0)` after every group change and then runs a second discovery. `Moment.capture()` in `moment.py:20` runs a third.

Incidental findings: `main.py` calls `main()` without an argument, so with `reload=True` — watchfiles then runs on the Pi as well. And renaming a moment in `moments_ui` does not persist, because `_save()` is never called.

## Target architecture

### 1. A device registry instead of discovery in the render path

The problem is not discovery as such, but discovery on every page load. The solution is a persistent registry that tracks devices by their **UID** (`RINCON_B8E937EE4EA001400` — it contains the MAC address, so it is stable across router and DHCP changes) and keeps the last known IP only as a cache.

Sequence at startup: ping all known IPs in parallel and check the UID. That costs one roundtrip of ~10 ms per device, runs concurrently and is therefore effectively instant. The decisive part is the self-healing mechanism: **as soon as a single speaker answers at a known IP, `device.all_zones` yields the entire household including all current IPs.** After a router change that shifts the addresses around, one hit is therefore enough to repair the rest.

Only when nothing at all answers — or at the push of a button in the UI — does a real search run, in the background and never in the render path:

1. `soco.discovery.discover()` via SSDP. Fast when multicast gets through (the speakers answered here in 84–390 ms).
2. If that comes back empty: `soco.discovery.scan_network()`. It scans the local subnet via TCP and, according to its docstring, is meant for exactly the case where multicast does not work — so for our wifi scenario on the Pi. Parameters: `max_threads` (default 256, better set to 32–64 on the Zero 2 W), `scan_timeout=0.5`, `min_netmask=24`.

With that, "find devices" becomes a normal feature in the app instead of a precondition for starting up, and fixed IPs are only the fallback that nobody needs.

### 2. Long-lived state in memory

A process-wide `SonosSystem` holds the complete state as a plain Python data structure: per player name, UID, volume, mute; per group coordinator, members, transport state and current track. The UI reads **exclusively** from this in-memory image and makes zero network calls while rendering. A page load is thereby independent of the network and the speakers, and practically instant — that is the single biggest gain for how the app feels.

### 3. Event subscriptions

Instead of polling, we subscribe to UPnP events. The relevant services:

| Service | Where | Provides |
|---|---|---|
| `RenderingControl` | every player | volume, mute (channel `Master`), later bass/treble/loudness |
| `AVTransport` | per coordinator | transport state, current track, position, queue changes |
| `ZoneGroupTopology` | one player is enough | grouping of the whole household |
| `GroupRenderingControl` | per coordinator | group volume (for the planned multi-speaker volume) |

Technically: `sub = device.renderingControl.subscribe(requested_timeout=600, auto_renew=True)`. SoCo starts an HTTP listener in a background thread for this, to which the speakers send `NOTIFY` requests; the default port is `config.EVENT_LISTENER_PORT = 1400`, and if it is taken SoCo moves upwards. On the Pi 1400 is free (that is the port *of the speakers*, not ours). If the Pi has several interfaces, `config.EVENT_ADVERTISE_IP` has to be set, or we may advertise the wrong address and events never arrive.

Important: a `ZoneGroupTopology` event means coordinators may have changed. The subscription manager has to react to that and move the `AVTransport` subscriptions accordingly. That is the only real state logic in the event handling and belongs in exactly one place.

### 4. Bridge from thread to asyncio to UI

Events land in `sub.events`, a `queue.Queue` filled from a foreign thread. The cleanest pragmatic route in NiceGUI: a `ui.timer(0.1, drain)` at app level that empties all queues with `get_nowait()`, updates the state and refreshes the affected refreshables when something changed. A granularity of 100 ms is imperceptible and it sidesteps every thread-safety discussion with the event loop. The alternative would be a reader thread with `loop.call_soon_threadsafe` — more control, more sources of error; only worth taking if the 100 ms ever get in the way.

The UI update should become fine-grained: not rebuilding the whole `speakers_ui` when one volume changes, but binding precisely (`bind_value_from` on the state object). Otherwise the whole page flickers on every event and open menus close.

### 5. Write path

All writing SoCo calls go through `asyncio.to_thread` so the event loop is never blocked. The UI does **not** wait for a confirmation and does not refresh either — the confirmation comes back as an event. With that, the `asyncio.sleep(1.0)` hack disappears without replacement.

What is new to solve is the echo problem: while you turn the knob, the speaker fires events with intermediate values that make the control jump back. Solution: a "pending write" per device with a target value and a timestamp; incoming volume events for that device are ignored until either the target value is confirmed or ~500 ms have passed. On top of that, throttle the knob writes (at most one SOAP call per ~100 ms, last value wins).

### 6. Robustness

*(implemented except for the points concerning the Pi)*

A watchdog timer (every 60 s, say) checks whether all subscriptions are still alive and rebuilds them otherwise. Necessary because speakers reboot, install firmware updates and wifi drops out. In addition a "stale" marker in the state: if a player has sent no event for longer than X minutes and does not answer a ping either, it is greyed out in the UI instead of being shown with outdated values. On process exit, explicitly `unsubscribe()` from all subscriptions — otherwise the speakers keep sending NOTIFYs into the void for minutes.

Devices are **not** dropped from the registry automatically in the process; they stay, greyed out: a speaker on a switched-off socket is the normal case, not an error. Cleaning up happens by hand only. The watchdog periodically includes a greyed-out player in the connection attempts again, so that it comes back on its own once it is switched on.

**As built:** a sign of life is both — an answered query *and* an incoming event. That is why `last_seen` does not simply come from the refresh: a speaker that is currently sending events must not be greyed out just because one query ran into a timeout. Only after `STALE_AFTER` (120 s) without any sign of life does `online` flip; a write error greys out immediately, because by then the proof is already there.

This becomes visible in two places: a speaker that cannot be reached but is still listed by the topology keeps its row in the group but loses its controls — a slider that moves nothing is worse than no slider. A speaker that has vanished from the topology entirely ends up in its own card below the groups, greyed out and labelled "not reachable". It explicitly does not disappear: a room that quietly takes its leave from the list looks like a bug in the app rather than an unplugged cable.

It comes back via `Registry.reconnect()`, which the refresh calls only when somebody is actually missing. It tries the known addresses in parallel (half a second for all of them together) and asks one that answers about the household — which additionally catches the speakers whose address has changed and which pinging the remembered IP would therefore never find. A real search remains the button in the UI; once a minute it would be far too expensive.

### 7. Rebuilding moments

Because the state is live in memory anyway, `capture()` becomes a pure dict copy: no discovery, no SOAP calls, immediate. That is the second big gain.

More important, though, is **what** a moment stores. Currently it is `get_current_track_info()['uri']`, and that is exactly where the problem comes from that moments stop working after a while. A comparison of two speakers in the running system, both on radioeins:

```
Bathroom: x-sonosapi-stream:tunein%3a9575?sid=303&flags=8224&sn=5
Bedroom:  x-rincon-mp3radio://http://f131.rndfnk.com/ard/rbb/radioeins/live/mp3/128/stream.mp3
          ?aggregator=tunein&cid=…&sid=…&token=3Kzgz7VwsReWjF7AssUfU6gCbfv29CIFh3FrunUeQIk&tvf=…
```

The first is a stable service reference, the second an already-resolved CDN URL with an expiring token and a fixed edge node. Store the second one in a moment and it is worthless once the token expires. On top of that comes a second expiry mechanism: `sn=` is the serial number of the linked service account. If a service is re-linked or migrated by Sonos, it changes and all stored URIs break. Both generations are visible in the favorites — older entries on `sid=333&sn=8` (TuneIn (New)), newer ones on `sid=303&sn=5` (Sonos Radio). That is almost certainly why moments had to be re-recorded.

Consequence: per group, a moment does not store the transport URI but a **source reference** as a tagged union:

| Type | Content | Robustness |
|---|---|---|
| `favorite` | title + item ID of the Sonos favorite | highest — Sonos maintains the favorites itself across account changes |
| `station` | title + ID of a TuneIn station | just as high — the anonymous service has no account binding that could expire |
| `uri` | transport URI along with metadata | the fallback for everything that is not a favorite |
| `queue` | queue contents as URI + DIDL per track, track number, position | for playlists and albums |
| `none` | nothing | the moment only sets grouping and volumes |

For the `queue` type, the content itself is stored rather than the container it came from: a speaker playing from its queue reports `x-rincon-queue:<uid>#0` as its transport URI — a pointer to itself that gives no clue which album or playlist filled it. Restoring works as in `soco.snapshot.Snapshot`, only with the recorded metadata, so that titles and cover art are preserved. The limit is 200 tracks (`moment.QUEUE_LIMIT`), and restoring clears the speaker's queue — there is no other way.

Resolution happens only when playing. If a source can no longer be resolved, the moment is marked in the UI as needing repair and the source can be picked anew, instead of silently doing nothing.

A moment is explicitly an **action**, not a state: it is fired and not observed afterwards. There is no reconciliation between the current situation and stored moments, and therefore no "active" moment either — which spares us the awkward question of how similar two sets of volumes have to be to count as the same moment.

When playing, a comparison does happen nonetheless, but only once and only to save work: instead of bluntly tearing the grouping down and rebuilding it, a pure function `plan(moment, state, favorites)` computes the difference between target and actual and emits only what really has to change. Three rules make that generally sound:

- **Who coordinates does not matter.** If the member set of a group matches, the group is accepted even if a different speaker holds the coordinator role. That is invisible to the user and would otherwise trigger constant needless rebuilds. The source then goes to the current coordinator.
- **Only skip when equality is proven.** An already-resolved stream URL cannot be matched against a favorite; in that case the source is set again. When in doubt, act rather than guess — worst case you end up with the old behaviour.
- **A moment only touches what it names.** Speakers it does not name are left alone. The one unavoidable exception: whoever is in a group with a named speaker and does not belong there has to leave it.

Because the reconciliation is only as good as the picture underlying it, a refresh runs first. And because the function is pure, it is testable without speakers — see `tests/test_plan.py`.

On restore, the current approach additionally has a genuine bug: `play_uri(group.uri)` replaces the queue with a single track. Anyone listening to a playlist loses it. The right way is the one `soco.snapshot.Snapshot` takes internally — playback relative to the queue via `x-rincon-queue:<UID>#0` plus track number and position, with a special case for radio streams. `Snapshot` itself is not serializable and is therefore no good for persisted moments, but we adopt the logic.

Also to be corrected is the order on restore: first establish the complete topology (all `unjoin`/`join`), then set volumes and mute, then start the transport. Currently the coordinator starts playback before the members have joined.

The storage format changes incompatibly as a result. With the handful of existing moments, re-recording is cheaper than a migration — simply discard old entries when loading and show a note in the UI.

## Picking sources instead of searching in the Sonos app

The goal is for a moment to be **assembled** in Sonos Moments rather than merely recorded: pick speakers, set volumes, choose a source — done, without the detour through the official app. What works for that has been tried out against the running system:

**Sonos favorites work immediately and without any authentication.** `music_library.get_sonos_favorites()` currently returns 23 entries, mostly radio stations (WDR 2/3/5, 1LIVE, FluxFM, Bremen Zwei, radioeins, SomaFM, Klassik Radio Piano, House FM …) plus one SoundCloud playlist. Since the sources are maintained there anyway, a simple favorites browser probably covers everyday use almost completely. Three entries are Sonos promo tiles without a playable resource ("Discover Sonos Radio", "Sonos Presents", "Trending Now") — those have to be filtered out when listing.

**The TuneIn search works immediately and without auth as well.** *(implemented — `model/tunein.py` and `ui/stations.py`)* The classic TuneIn service (`sid=254`) has auth type `Anonymous`. Search categories are `stations`, `shows`, `hosts`; we offer only `stations`. Browsing goes through `get_metadata()`, which returns the same tree as the Sonos app — and there the **raw ID from `metadata['id']`** must be used, not `item_id`: the latter carries an `0fffffff` prefix that the service does not accept back.

The fiddly part was playback, as expected, and the answer is not the one SoCo suggests. Tried out against the running system:

| URI form | Result |
|---|---|
| `x-sonosapi-stream:s25111?sid=254&sn=0` | plays |
| `soco://0fffffffs25111?sid=254&sn=0` (`sonos_uri_from_id()`) | UPnP Error 714 |
| `x-rincon-cpcontainer:0fffffffs25111` (the `uri` of the search result) | UPnP Error 714 |

Along with it, DIDL metadata with `object.item.audioItem.audioBroadcast` and the service descriptor `SA_RINCON65031_` has to be sent, or the speaker does not know whom to ask for the stream.

**Deliberately leave out `flags`.** With `flags=8224` the speaker resolves the station against the linked service and rewrites the URI to `sid=303&sn=5` — that is, to exactly the form with the account serial number that the old moments died of. Without `flags` it stays with the anonymous TuneIn service and therefore keeps working. That is why a station is not a `uri` moment but a source type of its own, `station`, which stores only the station ID and builds the URI from it when playing — without the network, and therefore without any way of becoming unresolvable.

**SoundCloud and Mixcloud need their own sign-in in our app.** Both currently answer with auth errors:

```
SoundCloud (sid=160, AppLink):    'Authentication failed: OAuth token expired or invalid'
Mixcloud   (sid=181, DeviceLink): 'Authorization for Mixcloud expired, is invalid or has not yet been completed'
```

SoCo supports that via `begin_authentication()` / `complete_authentication(link_code, link_device_id)` with a token store of our own that we would have to persist — the user is shown a URL and a code and confirms the linkage in the browser. Feasible, but a work package of its own including token refresh and error handling. Search categories would be SoundCloud `artists/albums/tracks/playlists` and Mixcloud `tags/Shows/Users`.

**Dependency:** the token store and the current `MusicService` API only exist from SoCo 0.31 onwards; the project currently pins `soco = "^0.30.4"`. So for the feature part, move up to 0.31.x.

Suggested order: favorites browser first (cheap, robust, covers everyday use), then the TuneIn search (also without auth), SoundCloud and Mixcloud last and only if the need persists.

## Rethinking the UI

*(implemented — `ui/rooms.py` and `ui/moments.py`; the section stays as the rationale)*

The existing UI has three assumptions built into it that the rebuild overturns, and that is the real reason to rethink it.

**First, moments are an appendage today.** Speaker tabs with all the controls at the top, a narrow two-column list with the moments at the bottom. A moment is a pure action — tap it, done — and therefore belongs somewhere prominent and easy to reach with a thumb, but not spread across the screen: buttons, not a wall of tiles. No second area, no navigation. Everything on one screen.

**Second, the tabs mirror the group topology, which from now on changes live underneath the UI.** Even today `speakers.py` has to catch at the end that `tabs.value` points at nothing; with events that happens constantly, because group keys and coordinators change as soon as somebody else regroups something. Tabs whose identity and number change behind your back are the wrong structure for that. Better is a continuous list of all rooms in which group membership is shown visually (indentation, a bracket, a shared header) rather than through navigation. Side effect: you see all rooms at once, which helps when regrouping anyway.

**Third, the UI does not show what is playing.** There is play/pause/stop, but neither station nor title. With `AVTransport` events both come practically for free, and it is exactly the information you otherwise open the official app for. "Kitchen: radioeins" per group is probably the biggest perceived jump in quality in the whole rebuild.

Along with that a moment editor, which follows from the source feature: pick rooms, set volumes, choose a source from favorites or search, save. With it, "create moment" replaces the detour through the Sonos app, and "re-capture" turns from the main route into a shortcut. *(Built as a dialog on a copy of the moment — one card per group with source selection, a play switch and all rooms to tick. Capture leads straight into it, so a new moment can still be adjusted before saving. Search as a source is still missing, see stage 5.)*

Small things for the phone: `ui.knob` is pretty on the desktop but fiddly with a thumb — a slider with a large hit area plus the existing +/− buttons is the better choice there. And since the UI updates live from now on, rendering has to be bound to the state in a fine-grained way, or open menus and dialogs close on every incoming event.

**As built:** one screen without navigation. At the top the rooms as one card per group — group name, station and title, play/pause and stop, favorites and group menu, and below that one row per speaker with mute, slider and +/−. At the bottom, in a fixed footer, the moments as an action bar: tapping plays, the attached menu shows the source and offers rename, re-record and delete; on the right the capture button, which lets the new moment be named right away. The tabs are gone, as is the knob.

**Decided:** there is no separate room view. The screen permanently shows what is playing where — one row per group with room names, station or title, transport state and volume — and above or below it the moments as an action bar. The status display is thereby also the feedback: after tapping a moment you see immediately that grouping, source and volumes have changed. That is exactly why no highlighting of an "active" moment is needed — and the part of the model that would have to reconcile the current situation with stored moments falls away entirely.

## Deployment on the Zero 2 W

The Zero 2 W (4× Cortex-A53, 1 GHz, 512 MB) copes with this load without trouble: Python with FastAPI and socketio sits at roughly 60–100 MB, the Quasar bundle is parsed by the phone and not by the Pi, and per interaction there is practically just one websocket message. If the Pi feels overwhelmed, in my experience these points are the likely causes:

- **Wifi power save.** On by default, regularly causes latency spikes of 100–300 ms and is the most common cause of "feels sluggish". Turn it off: `iw dev wlan0 set power_save off`, permanently via a systemd unit or a NetworkManager setting.
- **Undervoltage.** Check `vcgencmd get_throttled` and `dmesg | grep -i voltage`. A weak power supply or a thin micro-USB cable throttles the clock permanently, and that feels exactly like "hardware too slow".
- **Reload mode.** Make sure the service starts via the `sonos-moments` entry point (`main_without_reload`) and not via `python main.py`.
- **How it starts.** A systemd unit with `Restart=always` and `After=network-online.target`, logs to journald with a rate limit so the SD card does not get written full. As the command `uv run sonos-moments`; uv is available as a binary for aarch64, armv7 and armv6.
- **SD card.** Cheap cards with poor random writes slow down every restart and every log write. Cross-check with `hdparm -t` or `dd`.

Along with that the PWA cosmetics, so the whole thing feels like an app on the phone. *(implemented in `pwa.py`: a route for `manifest.json`, `ui.add_head_html` with `<link rel="manifest">`, `apple-mobile-web-app-capable`, `apple-mobile-web-app-status-bar-style` and `theme-color` matching the black header, plus `icon-192.png` and `icon-512.png` as static routes.)*

The icons are deliberately backed with opaque white: iOS puts a transparent home screen icon on black, and the black circle of the logo would vanish in it. Via iOS Safari that is enough for "Add to Home Screen" including full screen, even without HTTPS. Not on Android/Chrome: a real installation requires a secure context, and we serve over HTTP on the local network — there it stays a shortcut that opens in the browser. There is no offline capability either way, and none is needed, because without the local network the app cannot control anything anyway; a service worker (which Chrome would want to see for the installation in any case) fails on the same HTTP.

## Rewrite or step by step?

The question defuses itself on size: the project is 292 lines. Substantively it is a rewrite nonetheless, because almost nothing of the existing building blocks survives — `System` goes from a polling class to an event class, `Moment` gets a different data model, `Device` and `Group` lose their dual role, and the UI is being rethought anyway. What remains is `app.py` as scaffolding, persistence via `app.storage.general`, and the accumulated experience of which Quasar elements feel good.

The decisive reason for starting over at the model is a separation that is missing today: **live state** — what the speakers are doing right now, fed from events, ephemeral — versus **moment** — a desired state, persisted, described through source references. Currently `Moment` is both in one, snapshot format and restore instruction, and `System` mixes live devices with stored moments. Operating that separation into the existing dataclasses after the fact would be more work than writing them anew.

Not as a big bang all the same: the rebuild runs in the order below, and after each stage the app runs. At this size of codebase that costs almost nothing and spares us the classic rewrite trap of having nothing runnable for weeks. In practice that means: build the new model alongside the old one, move the UI over, delete the old — not replace everything in one go.

The UI rebuild belongs to stage 4 in time: only then is the data model in place that the new interface is meant to display, and you do not build it twice.

## Order of implementation

1. ~~**State layer and registry.**~~ *(done)* Device registry by UID with an IP cache and background search, process-wide state, UI renders without network calls, all SoCo calls in `to_thread`.
2. ~~**Event subscriptions.**~~ *(done)* Subscriptions for RenderingControl, AVTransport and ZoneGroupTopology, queue drain via timer, re-attaching on topology changes, bindings instead of a full refresh.
3. ~~**Write path.**~~ *(done)* Echo suppression, throttling, `sleep(1.0)` hack removed.
4. ~~**Moments and sources.**~~ *(done)* Source reference instead of transport URI, favorites menu, correct restore order, reconciliation instead of blunt restoring, UI rebuild, moment editor and queue-preserving capture.
5. ~~**TuneIn search.**~~ *(done)* Browsing and searching for radio stations directly in the app, as a source in the moment editor and for playing immediately from the room card.
6. ~~**Watchdog and deployment.**~~ *(done)* Stale marking, resubscribe logic, PWA manifest, and the board itself: freshly set up with `flash.sh`, `setup.sh` and `deploy.sh`, with the read-only overlay on, so the plug can be pulled. Wifi power save stays on deliberately — the board is idle most of the time and the energy matters more here than the occasional latency spike. Undervoltage has not been measured.
7. **Optional: SoundCloud and Mixcloud.** Auth flow with a token store.

Stages 1 to 3 belong together and add up to the actual rebuild; after that, stage 4 is the part with the greatest everyday benefit.

## Open questions

- Collect further feature requests (the roadmap in the README already lists group volume, alarms, timers, media links).
- Several simultaneous clients: the state is shared, so all devices see the same thing. Only UI details such as the selected tab stay per client in `app.storage.user`.
- Authentication: none so far. As long as it is only reachable on the local network that is probably fine — but decide it deliberately rather than leaving it implicit.
