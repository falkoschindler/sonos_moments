import soco
from nicegui import ui


def speakers_ui() -> None:
    zones = soco.discover()
    if not zones:
        ui.label('No Sonos speakers found.')
        return

    with ui.grid(columns='repeat(4, auto)').classes('items-center gap-x-1 gap-y-0 border shadow px-4 w-full overflow-hidden'):
        for zone in sorted(zones, key=lambda z: z.player_name):
            ui.label(zone.player_name).classes('text-lg font-bold')
            ui.checkbox(value=not zone.mute, on_change=lambda e, zone=zone: setattr(zone, 'mute', not e.value)) \
                .props('dense checked-icon="volume_up" unchecked-icon="volume_off"').classes('-mr-4')
            ui.knob(value=zone.volume, min=0, max=100, step=1, show_value=True,
                    on_change=lambda e, zone=zone: setattr(zone, 'volume', e.value))
            if zone.is_coordinator:
                with ui.button_group().props('flat dense'):
                    ui.button(icon='play_arrow', on_click=zone.play).props('flat dense')
                    ui.button(icon='pause', on_click=zone.pause).props('flat dense')
                    ui.button(icon='stop', on_click=zone.stop).props('flat dense')
            else:
                ui.element()
