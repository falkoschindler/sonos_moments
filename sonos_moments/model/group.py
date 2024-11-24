from dataclasses import dataclass
from typing import Literal

from .device import Device


@dataclass(kw_only=True, slots=True)
class Group:
    coordinator_uid: str
    members: dict[str, Device]
    state: Literal['PLAYING', 'PAUSED_PLAYBACK', 'STOPPED']
    uri: str
