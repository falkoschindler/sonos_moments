from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from nicegui import events, ui

from ..model import Device, Group, Moment, Source, System

NO_SOURCE = ''  # option for a moment that only sets grouping and levels
KEEP_SOURCE = '#keep'  # option for a source that is not one of the favorites


@dataclass(kw_only=True, slots=True)
class _Form:
    """What every part of the editor needs: the draft it changes and a way to redraw it."""
    system: System
    draft: Moment
    rooms: dict[str, str]
    refresh: Callable[..., Any]


async def edit_moment(system: System, moment: Moment) -> Moment | None:
    """Show a moment in a form and return the edited copy, or None when the dialog is dismissed.

    A moment is put together here instead of only being recorded, which is what makes it possible
    to build one without playing it first. Everything happens on a copy, so the stored moment is
    left alone until the form is saved.
    """
    draft = Moment.from_dict(moment.to_dict())
    form = _Form(system=system, draft=draft, rooms=_rooms(system, draft), refresh=lambda: None)

    @ui.refreshable
    def groups_ui() -> None:
        for group in draft.groups:
            _group_card(form, group)
    form.refresh = groups_ui.refresh

    def add_group() -> None:
        draft.groups.append(Group(coordinator_uid='', members={}, state='PLAYING', source=Source(kind='none')))
        groups_ui.refresh()

    with ui.dialog().props('persistent') as dialog, ui.card().classes('w-full gap-3'):
        ui.input('Name').bind_value(draft, 'name').props('outlined dense autofocus').classes('w-full')
        groups_ui()
        ui.button('Add a group', icon='sym_r_add', on_click=add_group).props('flat')
        with ui.row().classes('w-full justify-end'):
            ui.button('Cancel', on_click=dialog.close).props('flat')
            ui.button('Save', on_click=lambda: dialog.submit(True))
    try:
        if not await dialog:
            return None
    finally:
        dialog.delete()  # the dialog is created inside a refreshable slot and would pile up otherwise
    draft.groups = [group for group in draft.groups if group.members]
    return draft


def _rooms(system: System, moment: Moment) -> dict[str, str]:
    """All rooms the form can offer, by name. A moment may name speakers we have not seen yet."""
    names = {uid: player.name or uid for uid, player in system.state.players.items()}
    for group in moment.groups:
        for uid in group.members:
            names.setdefault(uid, uid)
    return dict(sorted(names.items(), key=lambda item: item[1]))


def _group_card(form: _Form, group: Group) -> None:
    """One group of the moment: which rooms belong to it, what it plays and how loud."""
    def remove() -> None:
        form.draft.groups.remove(group)
        form.refresh()

    with ui.card().classes('w-full p-3 gap-2'):
        with ui.row(align_items='center').classes('w-full gap-0 flex-nowrap'):
            title = ' + '.join(name for uid, name in form.rooms.items() if uid in group.members)
            ui.label(title or 'No rooms yet').classes('font-bold grow min-w-0 truncate overflow-hidden')
            ui.button(icon='sym_r_delete', on_click=remove).props('flat round dense')
        _source_select(form, group)
        _transport_switch(group)
        for uid in form.rooms:
            _room_row(form, group, uid)


def _source_select(form: _Form, group: Group) -> None:
    """Offer the favorites, plus whatever the moment already points at."""
    favorites = form.system.favorites
    options = {NO_SOURCE: 'Nothing (only grouping and volume)'}
    if group.source.kind == 'uri':
        # a raw stream URI is not in the favorites and can only be kept
        options[KEEP_SOURCE] = group.source.description or 'The captured source'
        value = KEEP_SOURCE
    else:
        value = group.source.item_id if group.source.kind == 'favorite' else NO_SOURCE
    options.update({favorite.item_id: favorite.title for favorite in favorites})
    if value not in options:
        options[value] = f'{group.source.title} (no longer available)'

    def select(e: events.ValueChangeEventArguments) -> None:
        favorite = next((favorite for favorite in favorites if favorite.item_id == e.value), None)
        if favorite is not None:
            group.source = Source(kind='favorite', title=favorite.title, item_id=favorite.item_id,
                                  uri=favorite.uri, meta=favorite.meta)
        elif e.value == NO_SOURCE:
            group.source = Source(kind='none')
        # every other option is the source the moment already has, so it stays as it is

    ui.select(options, value=value, label='Source', on_change=select) \
        .props('outlined dense options-dense').classes('w-full')


def _transport_switch(group: Group) -> None:
    ui.switch('Start playing', value=group.state == 'PLAYING',
              on_change=lambda e: setattr(group, 'state', 'PLAYING' if e.value else 'STOPPED'))


def _room_row(form: _Form, group: Group, uid: str) -> None:
    """A room with its levels, or just a checkbox as long as it is not part of this group."""
    def toggle(e: events.ValueChangeEventArguments) -> None:
        for other in form.draft.groups:
            other.members.pop(uid, None)  # a speaker can only play along in one group
        if e.value:
            player = form.system.state.players.get(uid)
            group.members[uid] = Device(uid=uid,
                                        volume=player.volume if player is not None else 20,
                                        mute=player.mute if player is not None else False)
        if group.coordinator_uid not in group.members:
            group.coordinator_uid = next(iter(group.members), '')
        form.refresh()

    device = group.members.get(uid)
    # the level gets a line of its own, because a slider squeezed in next to the name would be
    # exactly as fiddly as the knob it replaced
    with ui.column().classes('w-full gap-0'):
        with ui.row(align_items='center').classes('w-full gap-1 flex-nowrap'):
            ui.checkbox(value=device is not None, on_change=toggle).props('dense')
            ui.label(form.rooms[uid]).classes('grow min-w-0 truncate overflow-hidden')
            if device is None:
                return
            ui.label().bind_text_from(device, 'volume').classes('text-sm opacity-60')
            ui.button(on_click=lambda: setattr(device, 'mute', not device.mute)).props('flat round dense') \
                .bind_icon_from(device, 'mute',
                                backward=lambda mute: 'sym_r_volume_off' if mute else 'sym_r_volume_up')
        with ui.row(align_items='center').classes('w-full gap-1 flex-nowrap'):
            volume_down = ui.button(icon='sym_r_remove').props('flat round dense')
            volume = ui.slider(min=0, max=100, step=1).bind_value(device, 'volume') \
                .props('label thumb-size="28px" track-size="6px"').classes('grow mx-2')
            volume_up = ui.button(icon='sym_r_add').props('flat round dense')
            volume_down.on_click(lambda: volume.set_value(max(0, volume.value - 1)))
            volume_up.on_click(lambda: volume.set_value(min(100, volume.value + 1)))
