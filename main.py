#!/usr/bin/env python3
import argparse

from nicegui import ui

from sonos_moments import capture, moments_ui, speakers_ui


@ui.page('/')
def main():
    ui.colors(primary='black')

    with ui.header():
        ui.label('SONOS').classes('text-2xl')
        ui.label('Moments').classes('text-2xl font-thin')
        ui.space()
        ui.button(icon='sym_o_screenshot_region', on_click=lambda _: capture()).props('dense')

    speakers_ui()
    moments_ui()


parser = argparse.ArgumentParser('Sonos Moments', description='Control Sonos speakers in a local network.')
parser.add_argument('--port', type=int, default=8080)
args = parser.parse_args()

ui.run(title='Sonos Moments', favicon='icon.png', port=args.port)
