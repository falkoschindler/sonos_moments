import soco
from nicegui import ui


def speakers_ui() -> ui.grid:
    with ui.grid(columns='repeat(5, auto)').classes('items-center gap-y-0 border shadow px-4') as grid:
        for zone in sorted(soco.discover(), key=lambda z: z.player_name):
            ui.label(zone.player_name).classes('text-lg font-bold')
            ui.switch(value=not zone.mute, on_change=lambda e, zone=zone: setattr(zone, 'mute', not e.value)) \
                .props('dense checked-icon="volume_up" unchecked-icon="volume_off"')
            slider = ui.slider(value=zone.volume, min=0, max=100,
                               on_change=lambda e, zone=zone: setattr(zone, 'volume', e.value)) \
                .props('dense').classes('w-32')
            ui.number(min=0, max=100).bind_value(slider).classes('w-12').props('borderless dense')
            with ui.button_group().props('flat dense'):
                ui.button(icon='play_arrow', on_click=zone.play).props('flat')
                ui.button(icon='pause', on_click=zone.pause).props('flat')
                ui.button(icon='stop', on_click=zone.stop).props('flat')
    return grid
