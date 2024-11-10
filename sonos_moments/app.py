import argparse

from nicegui import ui

from .model import System
from .ui import moments_ui, speakers_ui

system = System()


@ui.page('/')
def main_page() -> None:
    ui.colors(primary='black')

    def capture() -> None:
        system.capture()
        moments_ui.refresh()

    with ui.header():
        ui.label('SONOS').classes('text-2xl')
        ui.label('Moments').classes('text-2xl font-thin')
        ui.space()
        ui.button(icon='sym_r_screenshot_region', on_click=capture).props('dense')

    system.update_devices()
    speakers_ui(system)
    moments_ui(system)


def main(reload: bool = True) -> None:
    parser = argparse.ArgumentParser('Sonos Moments', description='Control Sonos speakers in a local network.')
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    ui.run(title='Sonos Moments', favicon='icon.png', port=args.port, reload=reload, storage_secret='sonos-moments')


def main_without_reload() -> None:
    main(reload=False)
