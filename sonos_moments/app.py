import argparse
from pathlib import Path

from nicegui import app, ui

from . import pwa
from .model import System
from .ui import moments_ui, rooms_ui

EVENT_INTERVAL = 0.1  # how often the queues filled by the event listener thread are drained
REFRESH_INTERVAL = 60.0  # safety net in case we ever miss an event

system = System()

pwa.setup()


@app.on_startup
async def startup() -> None:
    system.on_topology_change.append(rooms_ui.refresh)
    await system.start()
    app.timer(EVENT_INTERVAL, system.handle_events)
    app.timer(REFRESH_INTERVAL, system.refresh)


@app.on_shutdown
async def shutdown() -> None:
    await system.shutdown()


@ui.page('/')
def main_page() -> None:
    ui.colors(primary='black')

    with ui.header().classes('items-center'):
        ui.label('SONOS').classes('text-2xl')
        ui.label('Moments').classes('text-2xl font-thin')
        ui.space()
        ui.button(icon='sym_r_search', on_click=system.search).props('dense flat color=white') \
            .tooltip('Look for speakers')

    # everything on one screen: what is playing where, and the moments within reach of a thumb
    with ui.column().classes('w-full max-w-2xl mx-auto p-3 gap-3'):
        rooms_ui(system)
    with ui.footer().classes('p-2'):
        moments_ui(system)


def main(reload: bool = True) -> None:
    parser = argparse.ArgumentParser('Sonos Moments', description='Control Sonos speakers in a local network.')
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    ui.run(title='Sonos Moments', favicon=Path(__file__).parent / 'icon.png',
           port=args.port, reload=reload, storage_secret='sonos-moments')


def main_without_reload() -> None:
    main(reload=False)
