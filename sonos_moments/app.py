import argparse

from nicegui import ui

from .moments import capture, moments_ui
from .speakers import speakers_ui


@ui.page('/')
def main_page() -> None:
    ui.colors(primary='black')

    with ui.header():
        ui.label('SONOS').classes('text-2xl')
        ui.label('Moments').classes('text-2xl font-thin')
        ui.space()
        ui.button(icon='sym_o_screenshot_region', on_click=lambda _: capture()).props('dense')

    speakers_ui()
    moments_ui()


def main(reload: bool = True) -> None:
    parser = argparse.ArgumentParser('Sonos Moments', description='Control Sonos speakers in a local network.')
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    ui.run(title='Sonos Moments', favicon='icon.png', port=args.port, reload=reload)


def main_without_reload() -> None:
    main(reload=False)
