from functools import partial

from nicegui import ui

from ..model import Moment, System
from .editor import edit_moment


@ui.refreshable
def moments_ui(system: System) -> None:
    """Render the moments as an action bar.

    A moment is an action, not a state: it is fired and afterwards not watched any further. So it
    is a button, not a tile that would have to show something about itself.
    """
    with ui.row(align_items='center').classes('w-full gap-2'):
        for moment in system.moments:
            _moment_button(system, moment)
        if not system.moments:
            ui.label('No moments yet').classes('opacity-70')
        ui.space()
        ui.button(icon='sym_r_screenshot_region', on_click=partial(_capture, system)) \
            .props('flat round color=white').tooltip('Capture the current state as a new moment')

    if system.discarded_moments:
        ui.label(f'{system.discarded_moments} moment(s) were captured in an older format '
                 'and had to be discarded. Please capture them again.') \
            .classes('text-xs text-orange-300')


def _moment_button(system: System, moment: Moment) -> None:
    async def play() -> None:
        steps = await system.play_moment(moment)
        if steps.is_empty:
            ui.notify(f'"{moment.name}" is already playing like this', type='info')
        moments_ui.refresh()  # a source may have turned out to be unresolvable

    async def edit() -> None:
        edited = await edit_moment(system, moment)
        if edited is not None:
            system.store(edited)
            moments_ui.refresh()

    async def recapture() -> None:
        await system.recapture(moment)
        moments_ui.refresh()

    def remove() -> None:
        system.remove(moment)
        moments_ui.refresh()

    unresolved = moment.uid in system.unresolved
    button = ui.dropdown_button(moment.name, split=True, on_click=play,
                                icon='sym_r_warning' if unresolved else None) \
        .props('flat no-caps color=white')
    with button:
        # what a moment plays belongs into the menu rather than into a tooltip: it has to be
        # readable on a phone, and a tooltip would cover the menu it belongs to
        if unresolved:
            ui.item_label('The source is no longer available. Re-capture this moment.') \
                .props('header').classes('text-orange-600 whitespace-normal max-w-64')
        elif moment.description:
            ui.item_label(moment.description).props('header').classes('whitespace-normal max-w-64')
        ui.item('Edit', on_click=edit)
        ui.item('Re-capture', on_click=recapture)
        ui.item('Delete', on_click=remove)


async def _capture(system: System) -> None:
    """Capture the current state and show it in the editor, so it can be named and adjusted."""
    captured = await system.capture()
    moment = await edit_moment(system, captured)
    if moment is not None:
        system.store(moment)
        moments_ui.refresh()
