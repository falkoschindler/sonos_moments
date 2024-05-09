#!/usr/bin/env python3
from nicegui import ui

from sonos_moments import capture, moments_ui, speakers_ui


@ui.page('/')
def main():
    ui.colors(primary='black')

    with ui.header():
        ui.label('SONOS').classes('text-2xl')
        ui.label('Moments').classes('text-2xl font-thin')
        ui.space()
        ui.button('Capture', icon='sym_o_screenshot_region', on_click=lambda _: capture())

    speakers_ui()
    moments_ui()


ui.run(title='Sonos Moments', favicon='icon.png')
