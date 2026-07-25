from dataclasses import dataclass
from typing import Self
from uuid import uuid4

import soco
from dataclasses_json.core import _asdict, _decode_dataclass

from .device import Device
from .group import Group


@dataclass(kw_only=True, slots=True)
class Moment:
    uid: str
    name: str
    groups: list[Group]

    @classmethod
    def capture(cls, devices: list[soco.SoCo], name: str = '') -> Self:
        """Capture the current state of the given speakers.

        Blocking; call from a thread.
        """
        moment = cls(uid=str(uuid4()), name=name, groups=[])
        if not devices:
            return moment

        for group in devices[0].all_groups:
            coordinator = group.coordinator
            moment.groups.append(Group(
                coordinator_uid=coordinator.uid,
                members={
                    member.uid: Device(
                        uid=member.uid,
                        volume=member.volume,
                        mute=member.mute,
                    )
                    for member in group.members
                },
                state=coordinator.get_current_transport_info().get('current_transport_state'),
                uri=coordinator.get_current_track_info().get('uri'),
            ))
        return moment

    def to_dict(self) -> dict:
        return _asdict(self, False)

    @classmethod
    def from_dict(cls, data: dict) -> Self:
        return _decode_dataclass(cls, data, False)
