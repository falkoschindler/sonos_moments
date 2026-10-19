from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from nicegui import ui

from ..model import Entry, Source, System

ROOT = ('', 'TuneIn')  # the crumb the directory always starts from


@dataclass(kw_only=True, slots=True)
class _Browser:
    """Where we are in the directory and what is on screen because of it."""
    system: System
    path: list[tuple[str, str]] = field(default_factory=lambda: [ROOT])
    entries: list[Entry] | None = None  # None while the service is being asked
    failed: bool = False
    term: str = ''
    refresh: Callable[..., Any] = lambda: None

    async def load(self) -> None:
        self.entries = None
        self.refresh()
        result = await self.system.search_stations(self.term) if self.term \
            else await self.system.browse_stations(self.path[-1][0])
        self.failed = result is None
        self.entries = result or []
        self.refresh()

    async def open_folder(self, entry: Entry) -> None:
        self.path.append((entry.entry_id, entry.title))
        await self.load()

    async def go_back(self, index: int) -> None:
        del self.path[index + 1:]
        await self.load()


async def choose_station(system: System) -> Source | None:
    """Browse and search TuneIn, and return the chosen station.

    This is what replaces the detour through the Sonos app. A station picked here is stored as a
    reference to the station, not as the stream it currently resolves to.
    """
    browser = _Browser(system=system)

    async def search(e: Any) -> None:
        browser.term = (e.value or '').strip()
        await browser.load()

    @ui.refreshable
    def body() -> None:
        _crumbs(browser)
        with ui.column().classes('w-full h-96 overflow-y-auto gap-0'):
            _entries(browser, dialog)
    browser.refresh = body.refresh

    with ui.dialog() as dialog, ui.card().classes('w-full max-w-md gap-2 p-3'):
        ui.input('Search stations', on_change=search) \
            .props('outlined dense clearable autofocus debounce=400').classes('w-full')
        body()
        with ui.row().classes('w-full justify-end'):
            ui.button('Cancel', on_click=dialog.close).props('flat')
    await browser.load()
    try:
        return await dialog
    finally:
        dialog.delete()  # the dialog is created inside a refreshable slot and would pile up otherwise


def _crumbs(browser: _Browser) -> None:
    """The trail, which doubles as the way back -- a phone has no other button for it."""
    if browser.term or len(browser.path) == 1:
        return
    with ui.row(align_items='center').classes('w-full gap-0 text-sm flex-wrap'):
        for index, (_, title) in enumerate(browser.path):
            if index:
                ui.label('/').classes('opacity-40 mx-1')
            ui.button(title, on_click=lambda index=index: browser.go_back(index)) \
                .props('flat dense no-caps size=sm')


def _entries(browser: _Browser, dialog: ui.dialog) -> None:
    if browser.entries is None:
        with ui.row(align_items='center').classes('p-4 gap-3'):
            ui.spinner()
            ui.label('Loading...')
    elif browser.failed:
        ui.label('TuneIn could not be reached.').classes('p-4 opacity-70')
    elif not browser.entries:
        ui.label('Nothing found.').classes('p-4 opacity-70')
    else:
        with ui.list().props('separator').classes('w-full'):
            for entry in browser.entries:
                _row(browser, dialog, entry)


def _row(browser: _Browser, dialog: ui.dialog, entry: Entry) -> None:
    async def choose() -> None:
        if entry.is_folder:
            await browser.open_folder(entry)
        else:
            dialog.submit(Source.station(entry.entry_id, entry.title))

    with ui.item(on_click=choose):
        with ui.item_section().props('avatar'):
            ui.icon('sym_r_folder' if entry.is_folder else 'sym_r_radio')
        with ui.item_section():
            ui.item_label(entry.title).classes('truncate')
