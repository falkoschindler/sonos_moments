from functools import partial

import soco
from nicegui import app, ui


@ui.refreshable
def moments_ui() -> None:
    with ui.grid(columns='repeat(2, auto)').classes('items-center border shadow px-4 py-2 w-full overflow-hidden'):
        moments = app.storage.general.get('moments', [])
        if moments:
            for moment in moments:
                ui.input().bind_value(moment, 'name').props('dense borderless input-class="text-lg font-bold"')
                with ui.dropdown_button(icon='play_arrow', split=True, on_click=partial(play, moment)).props('flat'):
                    ui.item('Re-capture', on_click=partial(capture, moment))
                    ui.item('Delete', on_click=partial(remove_moment, moment))
        else:
            ui.label('No moments captured yet').classes('text-lg')


def capture(moment: dict | None = None) -> None:
    moments = app.storage.general.get('moments', [])
    speakers = [
        {
            'name': zone.player_name,
            'ip': zone.ip_address,
            'volume': zone.volume,
            'mute': zone.mute,
            'uri': zone.get_current_track_info().get('uri'),
            'state': zone.get_current_transport_info().get('current_transport_state'),
            'is_coordinator': zone.is_coordinator,
        }
        for zone in soco.discover()
    ]
    if moment is None:
        moments.append({
            'name': f'Moment #{len(moments) + 1}',
            'speakers': speakers,
        })
    else:
        moment['speakers'] = speakers
    moments_ui.refresh()


def play(moment: dict) -> None:
    for speaker in moment['speakers']:
        zone = soco.SoCo(speaker['ip'])
        zone.volume = speaker['volume']
        zone.mute = speaker['mute']
        if speaker['is_coordinator']:
            zone.play_uri(speaker['uri'])
            if speaker['state'] == 'PLAYING':
                zone.play()
            elif speaker['state'] == 'PAUSED_PLAYBACK':
                zone.pause()
            elif speaker['state'] == 'STOPPED':
                zone.stop()


def remove_moment(moment: dict) -> None:
    moments: list = app.storage.general.setdefault('moments', [])
    moments.remove(moment)
    moments_ui.refresh()
