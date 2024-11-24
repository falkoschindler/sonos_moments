from nicegui import app, events, ui

from ..model import System


@ui.refreshable
def speakers_ui(system: System) -> None:
    if not system.devices:
        ui.label('No Sonos speakers found.')
        return

    with ui.tabs() as tabs:
        for key, devices in system.device_groups.items():
            coordinator = next((d for d in devices if d.is_coordinator), devices[0])
            label = coordinator.player_name
            if len(devices) > 1:
                label += f' + {len(devices) - 1}'
            ui.tab(key, label)

    with ui.tab_panels(tabs).bind_value(app.storage.user, 'group').classes('w-full'):
        for key, devices in system.device_groups.items():
            with ui.tab_panel(key).classes('gap-x-1 border w-full p-0 gap-y-0'):
                coordinator = next((d for d in devices if d.is_coordinator), devices[0])
                with ui.row(align_items='center').classes('p-4 w-full'):
                    with ui.button_group().props('flat'):
                        ui.button(icon='sym_r_play_arrow', on_click=coordinator.play).props('flat')
                        ui.button(icon='sym_r_pause', on_click=coordinator.pause).props('flat')
                        ui.button(icon='sym_r_stop', on_click=coordinator.stop).props('flat')
                    ui.space()
                    with ui.button(icon='sym_r_speaker_group').props('flat'):
                        with ui.menu():
                            for device in sorted(system.devices.values(),
                                                 key=lambda d: (d is not coordinator, d.player_name)):
                                with ui.menu_item():
                                    def update_group(e: events.ValueChangeEventArguments,
                                                     device=device,
                                                     coordinator=coordinator) -> None:
                                        if e.value:
                                            device.join(coordinator)
                                        else:
                                            device.unjoin()
                                        system.update_devices()
                                        speakers_ui.refresh()
                                    ui.checkbox(device.player_name, value=device in devices) \
                                        .on_value_change(update_group) \
                                        .set_enabled(device != coordinator)

                ui.separator()

                with ui.grid(columns='1fr auto').classes('items-center gap-y-0 w-full px-4'):
                    for device in sorted(devices, key=lambda d: (d is not coordinator, d.player_name)):
                        ui.label(device.player_name).classes('text-lg font-bold')
                        with ui.row(align_items='center'):
                            ui.checkbox(value=not device.mute) \
                                .on_value_change(lambda e, device=device: setattr(device, 'mute', not e.value)) \
                                .props('dense checked-icon="sym_r_volume_up" unchecked-icon="sym_r_volume_off"')
                            volume_down = ui.button(icon='sym_r_remove').props('flat')
                            volume = ui.knob(value=device.volume, min=0, max=100, step=1, show_value=True,
                                             on_change=lambda e, device=device: setattr(device, 'volume', e.value))
                            volume_up = ui.button(icon='sym_r_add').props('flat')
                            volume_down.on_click(lambda volume=volume: volume.set_value(volume.value - 1))
                            volume_up.on_click(lambda volume=volume: volume.set_value(volume.value + 1))

    if tabs.value not in system.device_groups:
        tabs.value = next(iter(system.device_groups))
