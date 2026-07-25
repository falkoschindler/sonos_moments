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


@binding.bindable_dataclass
class GroupState:
    """Live state of a group of speakers.

    Instances are replaced whenever the topology changes, which also triggers a UI rebuild.
    """
    coordinator_uid: str
    member_uids: list[str]
    transport_state: str = 'STOPPED'
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

    def group_of(self, uid: str) -> GroupState | None:
        return next((group for group in self.groups if uid in group.member_uids), None)

    @property
    def online_players(self) -> list[PlayerState]:
        return [player for player in self.players.values() if player.online]

    def sorted_members(self, group: GroupState) -> list[PlayerState]:
        """Members of a group, coordinator first, the rest by name."""
        members = [self.players[uid] for uid in group.member_uids if uid in self.players]
        return sorted(members, key=lambda p: (p.uid != group.coordinator_uid, p.name))
