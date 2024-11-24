
from itertools import groupby

import soco
from nicegui import app

from .moment import Moment


class System:

    def __init__(self) -> None:
        self.moments = [Moment.from_dict(moment) for moment in app.storage.general.get('moments', [])]
        self.devices: dict[str, soco.SoCo] = {}

    @property
    def device_groups(self) -> dict[str, list[soco.SoCo]]:
        return {k: list(v) for k, v in groupby(sorted(list(self.devices.values()),
                                                      key=lambda d: d.group.uid), key=lambda d: d.group.uid)}

    def update_devices(self) -> None:
        self.devices = {d.uid: d for d in soco.discover()}

    def play(self, moment: Moment) -> None:
        for group in moment.groups:
            coordinator = self.devices[group.coordinator_uid]
            for member_uid, member in group.members.items():
                device = self.devices[member_uid]
                device.volume = member.volume
                device.mute = member.mute
                if member_uid == group.coordinator_uid:
                    device.unjoin()
                    if group.uri:
                        device.play_uri(group.uri)
                    if group.state == 'PLAYING':
                        device.play()
                    if group.state == 'PAUSED_PLAYBACK':
                        device.pause()
                    if group.state == 'STOPPED':
                        device.stop()
                else:
                    device.join(coordinator)

    def capture(self) -> None:
        self.moments.append(Moment.capture(f'Moment #{len(self.moments) + 1}'))
        self._save()

    def recapture(self, moment: Moment) -> None:
        self.moments[self.moments.index(moment)] = Moment.capture(moment.name)
        self._save()

    def remove(self, moment: Moment) -> None:
        self.moments.remove(moment)
        self._save()

    def _save(self) -> None:
        app.storage.general.update(moments=[m.to_dict() for m in self.moments])
