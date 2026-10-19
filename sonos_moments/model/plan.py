from dataclasses import dataclass, field

from .group import Group
from .moment import Moment
from .source import Favorite, Source, match_key
from .state import GroupState, SystemState


@dataclass(kw_only=True, slots=True)
class Plan:
    """The difference between a moment and the current state.

    Computing this separately from carrying it out keeps the tricky part free of speakers: it is
    a pure function of the moment and the state, and the UI can tell what is going to happen.
    """
    unjoin: list[str] = field(default_factory=list)
    join: list[tuple[str, str]] = field(default_factory=list)
    volume: dict[str, int] = field(default_factory=dict)
    mute: dict[str, bool] = field(default_factory=dict)
    sources: dict[str, Source] = field(default_factory=dict)
    transport: dict[str, str] = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.unjoin or self.join or self.volume or self.mute or self.sources or self.transport)


def plan(moment: Moment, state: SystemState, favorites: list[Favorite]) -> Plan:
    """Work out what actually has to change to reach the moment.

    A moment only speaks about the speakers it names; everything else is left alone. The one
    exception is unavoidable: a speaker that shares a group with a named speaker has to leave it.
    """
    result = Plan()
    for group in moment.groups:
        members = set(group.members)
        current = state.group_of(group.coordinator_uid)
        # who coordinates a group is invisible to the user, so an otherwise correct grouping is
        # accepted as is instead of being torn down just to hand the role to someone else
        keeps_grouping = current is not None and set(current.member_uids) == members
        coordinator_uid = current.coordinator_uid if keeps_grouping else group.coordinator_uid
        if not keeps_grouping:
            _plan_grouping(result, state, coordinator_uid, members)
        _plan_levels(result, state, group)
        # after a rebuild the coordinator starts out empty, so nothing about the old state applies
        _plan_playback(result, group, coordinator_uid, current if keeps_grouping else None, favorites)
    return result


def _plan_grouping(result: Plan, state: SystemState, coordinator_uid: str, members: set[str]) -> None:
    current = state.group_of(coordinator_uid)
    if current is None:
        pass  # the speaker is unknown or offline, joining the others is all we can try
    elif current.coordinator_uid == coordinator_uid:
        result.unjoin.extend(sorted(uid for uid in current.member_uids if uid not in members))
    else:
        result.unjoin.append(coordinator_uid)  # it has to lead its own group from now on
    for uid in sorted(members - {coordinator_uid}):
        group_of_member = state.group_of(uid)
        if group_of_member is None or group_of_member.coordinator_uid != coordinator_uid:
            result.join.append((uid, coordinator_uid))


def _plan_levels(result: Plan, state: SystemState, group: Group) -> None:
    for uid, device in group.members.items():
        player = state.players.get(uid)
        if player is None or player.volume != device.volume:
            result.volume[uid] = device.volume
        if player is None or player.mute != device.mute:
            result.mute[uid] = device.mute


def _plan_playback(result: Plan, group: Group, coordinator_uid: str,
                   current: GroupState | None, favorites: list[Favorite]) -> None:
    if group.source.kind != 'none':
        resolved = group.source.resolve(favorites)
        if resolved is None:
            result.unresolved.append(coordinator_uid)
        elif current is None or not _is_same_source(current.uri, resolved):
            result.sources[coordinator_uid] = resolved
    if coordinator_uid in result.sources or current is None or current.transport_state != group.state:
        result.transport[coordinator_uid] = group.state


def _is_same_source(current_uri: str, wanted: Source) -> bool:
    """Only skip setting the source when the two are provably the same.

    A stream that has already been resolved to a CDN address never matches the favorite it came
    from, and a queue reports itself as ``x-rincon-queue:<uid>``, which says nothing about its
    contents. Setting the source again is cheap, guessing wrong is not.
    """
    if wanted.kind != 'uri':
        return False
    return bool(current_uri) and match_key(current_uri) == match_key(wanted.uri)
