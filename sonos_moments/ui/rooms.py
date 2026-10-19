from nicegui import events, ui

from ..model import GroupState, PlayerState, Source, System
from .stations import choose_station


@ui.refreshable
def rooms_ui(system: System) -> None:
    """Render every room from the in-memory state, without touching the network.

    All rooms are visible at once and group membership is drawn as a card instead of being
    expressed through tabs: the topology changes live underneath the UI now, and a navigation
    whose entries appear and vanish on their own is the wrong place to put it.
    """
    if system.state.searching:
        with ui.row(align_items='center').classes('p-4 gap-3'):
            ui.spinner()
            ui.label('Searching for speakers...')
        return

    if not system.state.groups:
        with ui.column().classes('p-4 gap-2 items-start'):
            ui.label('No Sonos speakers found.')
            ui.button('Search', icon='sym_r_search', on_click=system.search).props('flat')
        return

    for group in system.state.groups:
        _group_card(system, group)
    _absent_card(system.state.absent_players)


def _group_card(system: System, group: GroupState) -> None:
    members = system.state.sorted_members(group)
    with ui.card().classes('w-full p-0 gap-0'):
        with ui.row(align_items='center').classes('w-full p-3 gap-0 flex-nowrap'):
            with ui.column().classes('gap-0 grow min-w-0 overflow-hidden'):
                ui.label(_title(members)).classes('text-lg font-bold truncate')
                ui.label().classes('text-sm text-gray-500 truncate') \
                    .bind_text_from(group, 'description', backward=lambda text: text or 'Nothing playing')
            _transport(system, group)
            _favorites(system, group)
            _grouping(system, group)
        ui.separator()
        with ui.column().classes('w-full p-2 gap-1'):
            for member in members:
                _volume(system, member, with_name=len(members) > 1)


def _absent_card(players: list[PlayerState]) -> None:
    """List the speakers we cannot reach, greyed out rather than gone.

    A speaker on a socket that is switched off is the normal case, and a room that silently
    disappears from the list looks like a bug in the app rather than an unplugged speaker.
    """
    if not players:
        return
    with ui.card().classes('w-full p-3 gap-1 opacity-50'):
        for player in players:
            with ui.row(align_items='center').classes('w-full gap-2 flex-nowrap'):
                ui.icon('sym_r_wifi_off')
                ui.label(player.name or player.uid).classes('grow min-w-0 truncate')
                ui.label('not reachable').classes('text-sm')


def _title(members: list[PlayerState]) -> str:
    """Name a group without spelling out every room, because they are listed right below anyway."""
    if not members:
        return '?'
    if len(members) == 1:
        return members[0].name
    return f'{members[0].name} + {len(members) - 1}'


def _transport(system: System, group: GroupState) -> None:
    async def toggle() -> None:
        if group.is_playing:
            await system.pause(group.coordinator_uid)
        else:
            await system.play(group.coordinator_uid)
    ui.button(on_click=toggle).props('flat round') \
        .bind_icon_from(group, 'is_playing',
                        backward=lambda playing: 'sym_r_pause' if playing else 'sym_r_play_arrow')
    # stopping only makes sense while something is running, and the row is tight on a phone
    ui.button(icon='sym_r_stop', on_click=lambda: system.stop(group.coordinator_uid)).props('flat round') \
        .bind_visibility_from(group, 'transport_state', backward=lambda state: state != 'STOPPED')


def _favorites(system: System, group: GroupState) -> None:
    async def start(source: Source, coordinator_uid: str = group.coordinator_uid) -> None:
        if not await system.play_source(source, coordinator_uid):
            ui.notify(f'"{source.title}" could not be started. '
                      'Its music service may no longer be linked to your household.',
                      type='warning')

    async def search(coordinator_uid: str = group.coordinator_uid) -> None:
        source = await choose_station(system)
        if source is not None:
            await start(source, coordinator_uid)

    with ui.button(icon='sym_r_radio').props('flat round'), ui.menu().classes('max-h-96'):
        ui.item('Search stations...', on_click=search)
        ui.separator()
        if not system.favorites:
            ui.item('No favorites found')
        for favorite in system.favorites:
            source = Source(kind='uri', title=favorite.title, uri=favorite.uri, meta=favorite.meta)
            ui.item(favorite.title, on_click=lambda source=source: start(source))


def _grouping(system: System, group: GroupState) -> None:
    with ui.button(icon='sym_r_speaker_group').props('flat round'), ui.menu():
        for player in sorted(system.state.online_players, key=lambda p: p.name):
            with ui.menu_item():
                async def update_group(e: events.ValueChangeEventArguments, uid=player.uid) -> None:
                    if e.value:
                        await system.join(uid, group.coordinator_uid)
                    else:
                        await system.unjoin(uid)
                    # no refresh needed: the speakers report the new grouping as an event
                ui.checkbox(player.name, value=player.uid in group.member_uids) \
                    .on_value_change(update_group) \
                    .set_enabled(player.uid != group.coordinator_uid)


def _volume(system: System, player: PlayerState, *, with_name: bool) -> None:
    """One volume row per speaker: a slider with a thumb big enough for a thumb, plus fine steps.

    A speaker we cannot reach keeps its row but loses its controls: showing its last known volume
    as if it were live would invite dragging a slider that moves nothing.
    """
    dimmed = '' if player.online else ' opacity-50 pointer-events-none'
    with ui.row(align_items='center').classes(f'w-full gap-1 flex-nowrap{dimmed}'):
        if with_name:
            ui.label().bind_text_from(player, 'name').classes('w-24 shrink-0 truncate')
        ui.button(on_click=lambda: system.set_mute(player.uid, not player.mute)).props('flat round dense') \
            .bind_icon_from(player, 'mute', backward=lambda mute: 'sym_r_volume_off' if mute else 'sym_r_volume_up')
        volume_down = ui.button(icon='sym_r_remove').props('flat round dense')
        volume = ui.slider(min=0, max=100, step=1,
                           on_change=lambda e: system.set_volume(player.uid, int(e.value))) \
            .bind_value_from(player, 'volume') \
            .props('label thumb-size="28px" track-size="6px"').classes('grow mx-2')
        volume_up = ui.button(icon='sym_r_add').props('flat round dense')
        volume_down.on_click(lambda volume=volume: volume.set_value(max(0, volume.value - 1)))
        volume_up.on_click(lambda volume=volume: volume.set_value(min(100, volume.value + 1)))
