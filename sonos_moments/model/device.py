from dataclasses import dataclass


@dataclass(kw_only=True, slots=True)
class Device:
    uid: str
    volume: int
    mute: bool
