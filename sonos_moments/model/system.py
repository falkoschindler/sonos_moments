import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import soco
from nicegui import app

from .events import Subscriptions
from .moment import Moment
from .registry import Registry
from .source import Favorite, Source
from .state import GroupState, SystemState

log = logging.getLogger(__name__)

soco.config.REQUEST_TIMEOUT = 5.0  # the default of 20 s would freeze the app whenever a speaker is unplugged

WRITE_INTERVAL = 0.1  # minimum distance between two commands to the same speaker while dragging a knob
ECHO_TIMEOUT = 1.0  # how long a speaker may keep reporting outdated values after we have written

Topology = list[tuple[str, list[str]]]


@dataclass(kw_only=True, slots=True)
class Pending:
    """A value we have written and are still waiting to be confirmed by an event."""
    value: Any
    deadline: float


def _text(metadata: Any, attribute: str) -> str:
    """Read a field from event metadata, which is a DIDL object only when there is any.

    Speakers send an empty string when they have nothing to say, and ``getattr('', 'title')``
    happily returns the ``str.title`` method instead of falling back to the default.
    """
    if not isinstance(metadata, str):
        value = getattr(metadata, attribute, '')
        if isinstance(value, str):
            return value
    return ''


def _play(device: soco.SoCo) -> None:
    """Start playback, retrying while the speaker is still busy with a fresh stream.

    A speaker that has just been handed a new radio URI answers "transition not available"
    for a moment. Blocking; call from a thread.
    """
    for attempt in range(4):
        try:
            device.play()
            return
        except soco.exceptions.SoCoUPnPException:
            if attempt == 3:
                raise
            time.sleep(1.0)


class System:
    """Owns the connection to the speakers and keeps :class:`SystemState` up to date.

    Every call into SoCo blocks, so everything that touches the network runs in a thread.
    The UI only ever reads from ``state`` and therefore renders without any network access.
    """

    def __init__(self) -> None:
        self.state = SystemState()
        self.registry = Registry()
        self.subscriptions = Subscriptions()
        self.devices: dict[str, soco.SoCo] = {}
        self.moments: list[Moment] = []
        self.favorites: list[Favorite] = []
        self.discarded_moments = 0
        self.unresolved: set[str] = set()
        self.on_topology_change: list[Callable[[], None]] = []
        self._zone_group_state = ''
        self._pending: dict[tuple[str, str], Pending] = {}
        self._writers: set[str] = set()
        self._refresh_lock = asyncio.Lock()

    async def start(self) -> None:
        """Restore what we know from storage and connect to the speakers."""
        self.registry.load(app.storage.general.get('devices', []))
        self._load_moments()
        for entry in self.registry.entries.values():
            self.state.player(entry.uid, name=entry.name, ip=entry.ip)
        await self._connect(self.registry.connect)

    def _load_moments(self) -> None:
        """Load the stored moments, dropping the ones from before sources were introduced."""
        self.moments = []
        self.discarded_moments = 0
        for data in app.storage.general.get('moments', []):
            try:
                self.moments.append(Moment.from_dict(data))
            except Exception:
                self.discarded_moments += 1

    async def search(self) -> None:
        """Actively look for speakers, e.g. after a router change."""
        await self._connect(self.registry.search)

    async def load_favorites(self) -> None:
        """Read the Sonos favorites, which are the most robust way to point at a source."""
        if not self.devices:
            return
        favorites = await self._read(Favorite.read, next(iter(self.devices.values())))
        if favorites is not None:
            self.favorites = favorites
            self._notify()

    async def _connect(self, connect: Callable[[], list[soco.SoCo]]) -> None:
        self.state.searching = True
        self._notify()
        try:
            devices = await asyncio.to_thread(connect)
            self.devices = {device.uid: device for device in devices}
            app.storage.general['devices'] = self.registry.dump()
            for device in devices:
                self.state.player(device.uid, name=device.player_name, ip=device.ip_address)
        finally:
            self.state.searching = False
        await self.refresh()
        await self.load_favorites()

    async def refresh(self) -> None:
        """Read the current state of all speakers in parallel.

        Serialized, because a refresh spans several awaits and an incoming topology event must
        not swap the groups out from underneath a running one.
        """
        async with self._refresh_lock:
            await self._refresh()

    async def _refresh(self) -> None:
        if not self.devices:
            self._notify()
            return
        topology = await self._read(self._read_topology)
        readings = await asyncio.gather(*(self._read(self._read_player, device) for device in self.devices.values()))
        for reading in readings:
            if reading is None:
                continue
            uid, volume, mute = reading
            player = self.state.player(uid)
            player.volume = volume
            player.mute = mute
        online = {reading[0] for reading in readings if reading is not None}
        for player in self.state.players.values():
            player.online = player.uid in online
        if topology is None:
            topology = self._current_topology() if online else []
        await self._apply_topology(topology)
        await asyncio.to_thread(self.subscriptions.sync, self.devices,
                                {group.coordinator_uid for group in self.state.groups})

    async def handle_events(self) -> None:
        """Apply what the speakers have pushed to us. Called frequently, must stay cheap."""
        topology_changed = False
        for event in self.subscriptions.drain():
            if event.service == 'renderingControl':
                self._apply_rendering(event.uid, event.variables)
            elif event.service == 'avTransport':
                self._apply_playback(event.uid, event.variables)
            elif event.service == 'zoneGroupTopology':
                zone_group_state = str(event.variables.get('zone_group_state', ''))
                if zone_group_state != self._zone_group_state:
                    self._zone_group_state = zone_group_state
                    topology_changed = True
        if topology_changed:
            await self.refresh()

    def _apply_rendering(self, uid: str, variables: dict) -> None:
        player = self.state.player(uid)
        if 'volume' in variables:
            volume = int(variables['volume']['Master'])
            if self._accept(uid, 'volume', volume):
                player.volume = volume
        if 'mute' in variables:
            mute = variables['mute']['Master'] == '1'
            if self._accept(uid, 'mute', mute):
                player.mute = mute

    def _accept(self, uid: str, field: str, value: Any) -> bool:
        """Decide whether an incoming value is news or just an echo of what we are writing.

        While a knob is being dragged the speaker keeps reporting the values it has already
        passed. Applying those would make the knob jump backwards under the finger.
        """
        pending = self._pending.get((uid, field))
        if pending is None:
            return True
        if pending.value == value or time.monotonic() > pending.deadline:
            del self._pending[uid, field]
            return True
        return False

    def _apply_playback(self, uid: str, variables: dict) -> None:
        group = next((group for group in self.state.groups if group.coordinator_uid == uid), None)
        if group is None:
            return  # events from a speaker that is no longer a coordinator
        if 'transport_state' in variables:
            group.transport_state = variables['transport_state'] or 'STOPPED'
        if 'av_transport_uri_meta_data' in variables:
            group.channel = _text(variables['av_transport_uri_meta_data'], 'title')
        if 'current_track_meta_data' in variables:
            track = variables['current_track_meta_data']
            group.title = _text(track, 'title')
            group.artist = _text(track, 'creator')

    async def _apply_topology(self, topology: Topology) -> None:
        """Update the groups, rebuilding them only when the grouping actually changed."""
        changed = self._signature(topology) != self._signature(self._current_topology())
        if changed:
            groups = [GroupState(coordinator_uid=coordinator_uid, member_uids=member_uids)
                      for coordinator_uid, member_uids in topology]
            groups.sort(key=lambda group: self.state.player(group.coordinator_uid).name)
            self.state.groups = groups
        groups = list(self.state.groups)  # the reads below await, so work on a snapshot
        playbacks = await asyncio.gather(*(self._read(self._read_playback, group.coordinator_uid)
                                           for group in groups))
        for group, playback in zip(groups, playbacks, strict=True):
            if playback is None:
                continue
            group.transport_state, group.channel, group.title, group.artist = playback
        if changed:
            self._notify()

    def _current_topology(self) -> Topology:
        return [(group.coordinator_uid, group.member_uids) for group in self.state.groups]

    @staticmethod
    def _signature(topology: Topology) -> set[tuple[str, tuple[str, ...]]]:
        return {(coordinator_uid, tuple(sorted(member_uids))) for coordinator_uid, member_uids in topology}

    def _notify(self) -> None:
        for callback in self.on_topology_change:
            callback()

    async def _read(self, read: Callable, *args) -> Any:
        """Run a blocking read in a thread, treating an unreachable speaker as missing data."""
        try:
            return await asyncio.to_thread(read, *args)
        except Exception:
            return None

    def _read_topology(self) -> Topology:
        anchor = next(iter(self.devices.values()))
        # SoCo stops polling the topology as soon as a ZoneGroupTopology subscription exists and
        # expects the subscriber to keep the cache up to date, so we hand it a fresh payload.
        payload = anchor.zoneGroupTopology.GetZoneGroupState()['ZoneGroupState']
        anchor.zone_group_state.process_payload(payload=payload, source='poll', source_ip=anchor.ip_address)
        groups = [(group.coordinator.uid, [member.uid for member in group.members if member.uid in self.devices])
                  for group in anchor.all_groups]
        return [(coordinator_uid, member_uids) for coordinator_uid, member_uids in groups if member_uids]

    @staticmethod
    def _read_player(device: soco.SoCo) -> tuple[str, int, bool]:
        return device.uid, device.volume, device.mute

    def _read_playback(self, coordinator_uid: str) -> tuple[str, str, str, str]:
        device = self.devices[coordinator_uid]
        transport = device.get_current_transport_info().get('current_transport_state', 'STOPPED')
        media = device.get_current_media_info()
        track = device.get_current_track_info()
        return transport, media.get('channel', ''), track.get('title', ''), track.get('artist', '')

    async def set_volume(self, uid: str, volume: int) -> None:
        player = self.state.player(uid)
        if player.volume == volume:
            return  # nothing to do, and it keeps UI bindings from echoing values back to the speaker
        player.volume = volume
        self._expect(uid, 'volume', volume)
        await self._write_volume(uid)

    async def _write_volume(self, uid: str) -> None:
        """Write the current volume, coalescing the flood of values a dragged knob produces.

        Only one writer runs per speaker. It keeps going as long as the target moves, so the
        last value always reaches the speaker without sending every single step on the way.
        """
        if uid in self._writers:
            return
        self._writers.add(uid)
        try:
            while True:
                volume = self.state.player(uid).volume
                await self._write(lambda device, volume=volume: setattr(device, 'volume', volume), uid)
                await asyncio.sleep(WRITE_INTERVAL)
                if self.state.player(uid).volume == volume:
                    return
        finally:
            self._writers.discard(uid)

    async def set_mute(self, uid: str, mute: bool) -> None:
        player = self.state.player(uid)
        if player.mute == mute:
            return
        player.mute = mute
        self._expect(uid, 'mute', mute)
        await self._write(lambda device: setattr(device, 'mute', mute), uid)

    def _expect(self, uid: str, field: str, value: Any) -> None:
        self._pending[uid, field] = Pending(value=value, deadline=time.monotonic() + ECHO_TIMEOUT)

    async def play(self, uid: str) -> None:
        await self._write(_play, uid)

    async def pause(self, uid: str) -> None:
        await self._write(lambda device: device.pause(), uid)

    async def stop(self, uid: str) -> None:
        await self._write(lambda device: device.stop(), uid)

    async def join(self, uid: str, coordinator_uid: str) -> None:
        coordinator = self.devices[coordinator_uid]
        await self._write(lambda device: device.join(coordinator), uid)

    async def unjoin(self, uid: str) -> None:
        await self._write(lambda device: device.unjoin(), uid)

    async def _write(self, command: Callable[[soco.SoCo], None], uid: str) -> bool:
        """Send a command to a speaker without blocking the event loop. Returns whether it worked."""
        device = self.devices.get(uid)
        if device is None:
            return False
        try:
            await asyncio.to_thread(command, device)
            return True
        except soco.exceptions.SoCoUPnPException as e:
            # the speaker is fine but refused the command, e.g. because a music service is no
            # longer linked to the household and its URIs have become invalid
            log.warning('%s rejected a command: %s', self.state.player(uid).name, e)
            return False
        except Exception:
            log.exception('%s is unreachable', self.state.player(uid).name)
            self.state.player(uid).online = False
            return False

    async def play_moment(self, moment: Moment) -> None:
        """Restore a moment: first the grouping, then the volumes, then the playback.

        The order matters: members have to be in place before the coordinator starts playing,
        otherwise they miss the beginning.
        """
        await asyncio.gather(*(self.unjoin(group.coordinator_uid) for group in moment.groups))
        await asyncio.gather(*(self.join(member_uid, group.coordinator_uid)
                               for group in moment.groups
                               for member_uid in group.members
                               if member_uid != group.coordinator_uid))
        await asyncio.gather(*(command
                               for group in moment.groups
                               for member_uid, member in group.members.items()
                               for command in (self.set_volume(member_uid, member.volume),
                                               self.set_mute(member_uid, member.mute))))
        self.unresolved.discard(moment.uid)
        for group in moment.groups:
            resolved = group.source.resolve(self.favorites)
            if group.source.kind == 'none':
                pass
            elif resolved is None:
                self.unresolved.add(moment.uid)  # the favorite has disappeared
            else:
                uri, meta = resolved
                if not await self._write(lambda device, uri=uri, meta=meta: Source.select(device, uri, meta),
                                         group.coordinator_uid):
                    self.unresolved.add(moment.uid)  # the speaker refused the source, e.g. a dead service
            if group.state == 'PLAYING':
                await self.play(group.coordinator_uid)
            elif group.state == 'PAUSED_PLAYBACK':
                await self.pause(group.coordinator_uid)
            elif group.state == 'STOPPED':
                await self.stop(group.coordinator_uid)
        await self.refresh()

    async def play_favorite(self, favorite: Favorite, coordinator_uid: str) -> bool:
        """Start a favorite on a group, so that a source can be chosen without the Sonos app."""
        if not await self._write(lambda device: Source.select(device, favorite.uri, favorite.meta), coordinator_uid):
            return False
        await self.play(coordinator_uid)
        return True

    async def capture(self) -> None:
        moment = await asyncio.to_thread(Moment.capture, list(self.devices.values()), self.favorites,
                                         f'Moment #{len(self.moments) + 1}')
        self.moments.append(moment)
        self.save()

    async def recapture(self, moment: Moment) -> None:
        new_moment = await asyncio.to_thread(Moment.capture, list(self.devices.values()), self.favorites, moment.name)
        new_moment.uid = moment.uid
        self.moments[self.moments.index(moment)] = new_moment
        self.unresolved.discard(moment.uid)
        self.save()

    def remove(self, moment: Moment) -> None:
        self.moments.remove(moment)
        self.save()

    def save(self) -> None:
        app.storage.general['moments'] = [moment.to_dict() for moment in self.moments]

    async def shutdown(self) -> None:
        """Release the subscriptions, so the speakers stop sending events into the void."""
        await asyncio.to_thread(self.subscriptions.stop)
