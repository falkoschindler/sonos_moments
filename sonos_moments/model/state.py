from nicegui import binding


@binding.bindable_dataclass
class PlayerState:
    """Live state of a single speaker.

    Instances are created once per device and kept alive, so that UI bindings survive topology changes.
    """
    uid: str
    name: str = ''
    ip: str = ''
    volume: int = 0
    mute: bool = False
    online: bool = False
    last_seen: float = 0.0  # monotonic time of the last sign of life, be it an event or a read


@binding.bindable_dataclass
class GroupState:
    """Live state of a group of speakers.

    Instances are replaced whenever the topology changes, which also triggers a UI rebuild.
    """
    coordinator_uid: str
    member_uids: list[str]
    transport_state: str = 'STOPPED'
    uri: str = ''  # the source that was started, needed to tell whether a moment has to change it
    channel: str = ''
    title: str = ''
    artist: str = ''

    @property
    def description(self) -> str:
        """Human readable description of what is currently playing."""
        song = ' - '.join(part for part in (self.artist, self.title) if part)
        if self.channel and song and song != self.channel:
            return f'{self.channel}: {song}'
        return self.channel or song

    @property
    def is_playing(self) -> bool:
        return self.transport_state == 'PLAYING'


class SystemState:
    """Everything the UI needs to render, without touching the network."""

    def __init__(self) -> None:
        self.players: dict[str, PlayerState] = {}
        self.groups: list[GroupState] = []
        self.searching = False

    def player(self, uid: str, *, name: str = '', ip: str = '') -> PlayerState:
        """Return the state of a player, creating it on first sight."""
        if uid not in self.players:
            self.players[uid] = PlayerState(uid=uid, name=name, ip=ip)
        player = self.players[uid]
        if name:
            player.name = name
        if ip:
            player.ip = ip
        return player

    def seen(self, uid: str, now: float) -> bool:
        """Note that a speaker has made itself heard. Returns whether that is news.

        Both an answered read and an incoming event count, so a speaker that is busy pushing
        events is not greyed out just because one read happened to time out.
        """
        player = self.player(uid)
        player.last_seen = now
        was_offline = not player.online
        player.online = True
        return was_offline

    def lost(self, uid: str) -> bool:
        """Mark a speaker as unreachable right away. Returns whether that is news."""
        player = self.player(uid)
        was_online = player.online
        player.online = False
        return was_online

    def forget_silent(self, now: float, stale_after: float) -> bool:
        """Grey out speakers that have been quiet for too long. Returns whether anything changed.

        Showing the last known volume of a speaker that is no longer there is worse than showing
        nothing: it invites the user to drag a slider that will not move anything.
        """
        changed = False
        for player in self.players.values():
            if player.online and now - player.last_seen > stale_after:
                player.online = False
                changed = True
        return changed

    def group_of(self, uid: str) -> GroupState | None:
        return next((group for group in self.groups if uid in group.member_uids), None)

    @property
    def online_players(self) -> list[PlayerState]:
        return [player for player in self.players.values() if player.online]

    @property
    def absent_players(self) -> list[PlayerState]:
        """Speakers we know about that are in no group -- switched off, unplugged, or moved away.

        They stay in the list instead of vanishing: a speaker on a socket that is turned off is
        the normal case, not an error, and it should come back on its own.
        """
        return sorted((player for player in self.players.values()
                       if not player.online and self.group_of(player.uid) is None),
                      key=lambda player: player.name or player.uid)

    def sorted_members(self, group: GroupState) -> list[PlayerState]:
        """Members of a group, coordinator first, the rest by name."""
        members = [self.players[uid] for uid in group.member_uids if uid in self.players]
        return sorted(members, key=lambda p: (p.uid != group.coordinator_uid, p.name))
