from nicegui import app, ui

from ..model import System


def speakers_ui(system: System) -> None:
    if not system.devices:
        ui.label('No Sonos speakers found.')
        return

    with ui.tabs() as tabs:
        for key, devices in system.device_groups.items():
            coordinator = next((d for d in devices if d.is_coordinator), None)
            assert coordinator is not None
            label = coordinator.player_name
            if len(devices) > 1:
                label += f' + {len(devices) - 1}'
            ui.tab(key, label)

    with ui.tab_panels(tabs).bind_value(app.storage.user, 'group').classes('w-full'):
        for key, devices in system.device_groups.items():
            with ui.tab_panel(key).classes('gap-x-1 border shadow w-full p-0 gap-y-0'):
                coordinator = next((d for d in devices if d.is_coordinator), None)
                assert coordinator is not None
                with ui.button_group().props('flat').classes('m-4'):
                    ui.button(icon='play_arrow', on_click=coordinator.play).props('flat')
                    ui.button(icon='pause', on_click=coordinator.pause).props('flat')
                    ui.button(icon='stop', on_click=coordinator.stop).props('flat')
                ui.separator()
                with ui.grid(columns='repeat(2, auto)').classes('items-center gap-y-0 w-full px-4'):
                    for device in devices:
                        ui.label(device.player_name).classes('text-lg font-bold')
                        with ui.row(align_items='center'):
                            ui.checkbox(value=not device.mute) \
                                .on_value_change(lambda e, device=device: setattr(device, 'mute', not e.value)) \
                                .props('dense checked-icon="volume_up" unchecked-icon="volume_off"')
                            volume_down = ui.button(icon='remove').props('flat')
                            volume = ui.knob(value=device.volume, min=0, max=100, step=1, show_value=True,
                                             on_change=lambda e, device=device: setattr(device, 'volume', e.value))
                            volume_up = ui.button(icon='add').props('flat')
                            volume_down.on_click(lambda volume=volume: volume.set_value(volume.value - 1))
                            volume_up.on_click(lambda volume=volume: volume.set_value(volume.value + 1))
