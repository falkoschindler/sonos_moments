from functools import partial

from nicegui import ui

from ..model import Moment, System


@ui.refreshable
def moments_ui(system: System) -> None:
    async def play(moment: Moment) -> None:
        steps = await system.play_moment(moment)
        if steps.is_empty:
            ui.notify(f'"{moment.name}" is already playing like this', type='info')
        moments_ui.refresh()  # a source may have turned out to be unresolvable

    async def recapture(moment: Moment) -> None:
        await system.recapture(moment)
        moments_ui.refresh()

    def remove_moment(moment: Moment) -> None:
        system.remove(moment)
        moments_ui.refresh()

    with ui.grid(columns='auto 1fr auto').classes('items-center border px-4 py-2 w-full'):
        if system.moments:
            for moment in system.moments:
                ui.input(on_change=system.save).bind_value(moment, 'name') \
                    .props('dense borderless input-class="text-lg font-bold"')
                with ui.row(align_items='center').classes('gap-1 min-w-0'):
                    if moment.uid in system.unresolved:
                        ui.icon('sym_r_warning').classes('text-orange-500') \
                            .tooltip('The source is no longer available. Re-capture this moment.')
                    ui.label(moment.description).classes('text-sm text-gray-500 truncate')
                with ui.dropdown_button(icon='sym_r_play_arrow', split=True,
                                        on_click=partial(play, moment)).props('flat'):
                    ui.item('Re-capture', on_click=partial(recapture, moment))
                    ui.item('Delete', on_click=partial(remove_moment, moment))
        else:
            ui.label('No moments captured yet').classes('text-lg col-span-3')

    if system.discarded_moments:
        ui.label(f'{system.discarded_moments} moment(s) were captured in an older format '
                 'and had to be discarded. Please capture them again.') \
            .classes('text-sm text-orange-600 px-4')
