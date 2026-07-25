from dataclasses import dataclass
from typing import Self
from uuid import uuid4

import soco
from dataclasses_json.core import _asdict, _decode_dataclass
from soco.data_structures_entry import from_didl_string

from .device import Device
from .group import Group
from .source import Favorite, Source


def _title_of(meta: str) -> str:
    """Pull the name of the source, e.g. the radio station, out of its DIDL metadata."""
    if not meta:
        return ''
    try:
        return from_didl_string(meta)[0].title
    except Exception:
        return ''


@dataclass(kw_only=True, slots=True)
class Moment:
    uid: str
    name: str
    groups: list[Group]

    @classmethod
    def capture(cls, devices: list[soco.SoCo], favorites: list[Favorite], name: str = '') -> Self:
        """Capture the current state of the given speakers.

        Blocking; call from a thread.
        """
        moment = cls(uid=str(uuid4()), name=name, groups=[])
        if not devices:
            return moment

        for group in devices[0].all_groups:
            coordinator = group.coordinator
            media = coordinator.avTransport.GetMediaInfo([('InstanceID', 0)])
            uri = media.get('CurrentURI', '')
            meta = media.get('CurrentURIMetaData', '')
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
                # the media info holds the source that was started, the track info only the
                # resolved stream of this moment, which stops working after a while
                source=Source.capture(uri=uri, meta=meta, title=_title_of(meta), favorites=favorites),
            ))
        return moment

    @property
    def description(self) -> str:
        sources = [group.source.description for group in self.groups if group.source.description]
        return ', '.join(dict.fromkeys(sources))

    def to_dict(self) -> dict:
        return _asdict(self, False)

    @classmethod
    def from_dict(cls, data: dict) -> Self:
        if any('source' not in group for group in data.get('groups', [])):
            raise ValueError('moment was captured before sources were introduced')
        return _decode_dataclass(cls, data, False)
