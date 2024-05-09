#!/usr/bin/env python3
import soco
from nicegui import ui

ui.colors(primary='DarkOrange')
with ui.row():
    for zone in sorted(soco.discover(), key=lambda z: z.player_name):
        with ui.card().tight().props('flat bordered').classes('items-stretch'):
            with ui.card_section().classes('bg-primary'):
                ui.label(zone.player_name).classes('text-lg text-white')
            with ui.card_section().classes('bg-[SeaShell]'):
                with ui.row(wrap=False).classes('items-center'):
                    slider = ui.slider(value=zone.volume, min=0, max=100,
                                       on_change=lambda e, zone=zone: setattr(zone, 'volume', e.value))
                    ui.number().bind_value(slider).classes('w-16').props('borderless')
                ui.switch(value=not zone.mute, on_change=lambda e, zone=zone: setattr(zone, 'mute', not e.value))
                with ui.button_group().props('flat'):
                    ui.button(icon='play_arrow', on_click=zone.play).props('flat')
                    ui.button(icon='pause', on_click=zone.pause).props('flat')
                    ui.button(icon='stop', on_click=zone.stop).props('flat')

with ui.card().tight().props('flat bordered').classes('items-stretch'):
    with ui.card_section().classes('bg-primary'):
        ui.label('Moments').classes('text-lg text-white')
    with ui.card_section().classes('bg-[SeaShell]'):
        ui.label('...')

ui.run(title='Sonos Moments')
