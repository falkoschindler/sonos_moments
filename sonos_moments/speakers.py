import soco
from nicegui import ui


def speakers_ui() -> None:
    with ui.grid(columns='repeat(4, auto)').classes('items-center gap-x-1 gap-y-0 border shadow px-4 w-full overflow-hidden'):
        for zone in sorted(soco.discover(), key=lambda z: z.player_name):
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
                    ui.button('+30s', on_click=lambda zone=zone: skip(zone, 30)).props('flat dense')
            else:
                ui.element()


def skip(zone: soco.SoCo, d_seconds: int) -> None:
    position = zone.get_current_track_info()['position']  # hh:mm:ss
    hours, minutes, seconds = map(int, position.split(':'))
    seconds += d_seconds
    minutes += seconds // 60
    seconds %= 60
    hours += minutes // 60
    minutes %= 60
    zone.seek(f'{hours:02d}:{minutes:02d}:{seconds:02d}')
