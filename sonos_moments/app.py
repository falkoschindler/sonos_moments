import argparse

from nicegui import app, ui

from .model import System
from .ui import moments_ui, speakers_ui

REFRESH_INTERVAL = 5.0

system = System()


@app.on_startup
async def startup() -> None:
    system.on_topology_change.append(speakers_ui.refresh)
    await system.start()
    app.timer(REFRESH_INTERVAL, system.refresh)


@ui.page('/')
def main_page() -> None:
    ui.colors(primary='black')

    async def capture() -> None:
        await system.capture()
        moments_ui.refresh()

    with ui.header():
        ui.label('SONOS').classes('text-2xl')
        ui.label('Moments').classes('text-2xl font-thin')
        ui.space()
        ui.button(icon='sym_r_search', on_click=system.search).props('dense flat color=white')
        ui.button(icon='sym_r_screenshot_region', on_click=capture).props('dense')

    speakers_ui(system, app.storage.user)
    moments_ui(system)


def main(reload: bool = True) -> None:
    parser = argparse.ArgumentParser('Sonos Moments', description='Control Sonos speakers in a local network.')
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    ui.run(title='Sonos Moments', favicon='icon.png', port=args.port, reload=reload, storage_secret='sonos-moments')


def main_without_reload() -> None:
    main(reload=False)
