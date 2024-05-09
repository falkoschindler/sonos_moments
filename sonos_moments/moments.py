from functools import partial

from nicegui import app, ui


@ui.refreshable
def moments_ui() -> ui.grid:
    with ui.grid(columns='repeat(2, auto)').classes('items-center border shadow px-4 py-2') as grid:
        for moment in app.storage.general.get('moments', []):
            ui.input().bind_value(moment, 'name').props('dense borderless input-class="text-lg font-bold"')
            with ui.dropdown_button(icon='play_arrow', split=True, on_click=partial(play, moment)).props('flat'):
                ui.item('Re-capture', on_click=partial(recapture, moment))
                ui.item('Delete', on_click=partial(remove_moment, moment))
    return grid


def capture() -> None:
    moments: list = app.storage.general.setdefault('moments', [])
    moments.append({
        'name': f'Moment #{len(moments) + 1}',
    })
    moments_ui.refresh()


def play(moment: dict) -> None:
    pass


def recapture(moment: dict) -> None:
    pass


def remove_moment(moment: dict) -> None:
    moments: list = app.storage.general.setdefault('moments', [])
    moments.remove(moment)
    moments_ui.refresh()
