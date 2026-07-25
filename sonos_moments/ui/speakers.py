from nicegui import events, ui

from ..model import GroupState, System


@ui.refreshable
def speakers_ui(system: System, storage: dict) -> None:
    """Render the speakers from the in-memory state, without touching the network.

    The user storage is passed in rather than looked up, because a refresh can be triggered from a
    background task, where there is no request context to resolve ``app.storage.user``.
    """
    if system.state.searching:
        with ui.row(align_items='center').classes('p-4'):
            ui.spinner()
            ui.label('Searching for speakers...')
        return

    if not system.state.groups:
        with ui.column().classes('p-4 gap-2'):
            ui.label('No Sonos speakers found.')
            ui.button('Search', icon='sym_r_search', on_click=system.search).props('flat')
        return

    with ui.tabs() as tabs:
        for group in system.state.groups:
            members = system.state.sorted_members(group)
            label = members[0].name if members else '?'
            if len(members) > 1:
                label += f' + {len(members) - 1}'
            ui.tab(group.coordinator_uid, label)

    with ui.tab_panels(tabs).bind_value(storage, 'group').classes('w-full'):
        for group in system.state.groups:
            with ui.tab_panel(group.coordinator_uid).classes('gap-x-1 border w-full p-0 gap-y-0'):
                _group_panel(system, group)

    if tabs.value not in [group.coordinator_uid for group in system.state.groups]:
        tabs.value = system.state.groups[0].coordinator_uid


def _group_panel(system: System, group: GroupState) -> None:
    with ui.row(align_items='center').classes('p-4 w-full'):
        with ui.button_group().props('flat'):
            ui.button(icon='sym_r_play_arrow', on_click=lambda: system.play(group.coordinator_uid)).props('flat')
            ui.button(icon='sym_r_pause', on_click=lambda: system.pause(group.coordinator_uid)).props('flat')
            ui.button(icon='sym_r_stop', on_click=lambda: system.stop(group.coordinator_uid)).props('flat')
        ui.label().bind_text_from(group, 'description').classes('text-sm text-gray-500 truncate')
        ui.space()
        with ui.button(icon='sym_r_speaker_group').props('flat'), ui.menu():
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
    ui.separator()

    with ui.grid(columns='1fr auto').classes('items-center gap-y-0 w-full px-4'):
        for player in system.state.sorted_members(group):
            ui.label().bind_text_from(player, 'name').classes('text-lg font-bold')
            with ui.row(align_items='center'):
                ui.checkbox(on_change=lambda e, uid=player.uid: system.set_mute(uid, not e.value)) \
                    .bind_value_from(player, 'mute', backward=lambda mute: not mute) \
                    .props('dense checked-icon="sym_r_volume_up" unchecked-icon="sym_r_volume_off"')
                volume_down = ui.button(icon='sym_r_remove').props('flat')
                volume = ui.knob(min=0, max=100, step=1, show_value=True,
                                 on_change=lambda e, uid=player.uid: system.set_volume(uid, int(e.value))) \
                    .bind_value_from(player, 'volume')
                volume_up = ui.button(icon='sym_r_add').props('flat')
                volume_down.on_click(lambda volume=volume: volume.set_value(max(0, volume.value - 1)))
                volume_up.on_click(lambda volume=volume: volume.set_value(min(100, volume.value + 1)))
