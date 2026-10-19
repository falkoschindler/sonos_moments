import socket
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass

import soco
from soco.discovery import scan_network

SONOS_PORT = 1400
PROBE_TIMEOUT = 0.5
SEARCH_TIMEOUT = 3.0
SCAN_THREADS = 64  # the soco default of 256 is too much for a Raspberry Pi Zero


@dataclass(kw_only=True, slots=True)
class DeviceEntry:
    """A device we have seen before. The UID is stable, the IP is only a cache."""
    uid: str
    name: str
    ip: str


class Registry:
    """Keeps track of known speakers across restarts and IP changes.

    Speakers are identified by their UID, which contains the MAC address and therefore survives
    router changes. The last known IP is stored as a shortcut only: if a single speaker can be
    reached, it tells us the current addresses of all the others.
    """

    def __init__(self) -> None:
        self.entries: dict[str, DeviceEntry] = {}

    def load(self, data: list[dict]) -> None:
        self.entries = {entry['uid']: DeviceEntry(**entry) for entry in data}

    def dump(self) -> list[dict]:
        return [asdict(entry) for entry in self.entries.values()]

    def remember(self, devices: list[soco.SoCo]) -> None:
        for device in devices:
            self.entries[device.uid] = DeviceEntry(uid=device.uid, name=device.player_name, ip=device.ip_address)

    def connect(self) -> list[soco.SoCo]:
        """Find all speakers of the household, starting from what we already know.

        Blocking; call from a thread. Returns an empty list if nothing could be reached at all.
        """
        anchor = next(iter(self._probe_known()), None)
        if anchor is None:
            anchor = self._search()
        if anchor is None:
            return []
        devices = self._household(anchor)
        self.remember(devices)
        return devices

    def search(self) -> list[soco.SoCo]:
        """Actively look for speakers, ignoring what we already know.

        Blocking; call from a thread.
        """
        anchor = self._search()
        if anchor is None:
            return []
        devices = self._household(anchor)
        self.remember(devices)
        return devices

    def reconnect(self) -> list[soco.SoCo]:
        """Try to reach the known speakers again, without a full search.

        Cheap enough to run periodically: one short TCP probe per speaker, all at once. Asking a
        speaker that answers about the household on top of that catches the ones whose address
        has changed, because a probe of the remembered IP cannot find those.

        Blocking; call from a thread.
        """
        devices = {device.uid: device for device in self._probe_known()}
        if devices:
            for device in self._household(next(iter(devices.values()))):
                devices.setdefault(device.uid, device)
        self.remember(list(devices.values()))
        return sorted(devices.values(), key=lambda device: device.player_name)

    def _probe_known(self) -> list[soco.SoCo]:
        """Return every known speaker that still answers under its remembered IP."""
        if not self.entries:
            return []
        with ThreadPoolExecutor(max_workers=len(self.entries)) as executor:
            results = executor.map(self._probe, list(self.entries.values()))
        return [device for device in results if device is not None]

    @staticmethod
    def _probe(entry: DeviceEntry) -> soco.SoCo | None:
        """Check whether the remembered IP still belongs to the same speaker."""
        try:
            with socket.create_connection((entry.ip, SONOS_PORT), timeout=PROBE_TIMEOUT):
                pass
            device = soco.SoCo(entry.ip)
            return device if device.uid == entry.uid else None
        except Exception:
            return None

    @staticmethod
    def _search() -> soco.SoCo | None:
        """Look for any speaker via SSDP, falling back to a scan of the local network.

        The scan exists because multicast is unreliable over Wi-Fi, which is exactly the
        situation on a Raspberry Pi Zero.
        """
        zones = soco.discover(timeout=SEARCH_TIMEOUT)
        if not zones:
            zones = scan_network(max_threads=SCAN_THREADS)
        return next(iter(zones), None) if zones else None

    @staticmethod
    def _household(anchor: soco.SoCo) -> list[soco.SoCo]:
        """Ask a reachable speaker about all the others."""
        try:
            return sorted(anchor.visible_zones, key=lambda device: device.player_name)
        except Exception:
            return [anchor]
