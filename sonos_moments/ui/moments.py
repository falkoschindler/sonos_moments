from functools import partial

from nicegui import ui

from ..model import Moment, System


@ui.refreshable
def moments_ui(system: System) -> None:
    def recapture(moment: Moment) -> None:
        system.recapture(moment)
        moments_ui.refresh()

    def remove_moment(moment: Moment) -> None:
        system.remove(moment)
        moments_ui.refresh()

    with ui.grid(columns='repeat(2, auto)').classes('items-center border shadow px-4 py-2 w-full overflow-hidden'):
        if system.moments:
            for moment in system.moments:
                ui.input().bind_value(moment, 'name').props('dense borderless input-class="text-lg font-bold"')
                with ui.dropdown_button(icon='play_arrow', split=True,
                                        on_click=partial(system.play, moment)).props('flat'):
                    ui.item('Re-capture', on_click=partial(recapture, moment))
                    ui.item('Delete', on_click=partial(remove_moment, moment))
        else:
            ui.label('No moments captured yet').classes('text-lg')
