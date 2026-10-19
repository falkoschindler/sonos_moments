import queue
from dataclasses import dataclass

import soco
from soco.events import Subscription, event_listener

PLAYER_SERVICES = ('renderingControl',)
COORDINATOR_SERVICES = ('avTransport',)
HOUSEHOLD_SERVICES = ('zoneGroupTopology',)
TIMEOUT = 600


@dataclass(kw_only=True, slots=True)
class Event:
    uid: str
    service: str
    variables: dict


class Subscriptions:
    """Keeps UPnP event subscriptions in sync with the current topology.

    The speakers push changes to an HTTP listener that SoCo runs in a background thread, from
    where they end up in a queue per subscription. Nothing here touches the event loop, so all
    methods except :meth:`drain` block and belong in a thread.
    """

    def __init__(self) -> None:
        self.subscriptions: dict[tuple[str, str], Subscription] = {}

    def sync(self, devices: dict[str, soco.SoCo], coordinator_uids: set[str]) -> None:
        """Subscribe to what we need, drop what we do not, and renew what has died."""
        wanted = {(uid, service) for uid in devices for service in PLAYER_SERVICES}
        wanted |= {(uid, service) for uid in coordinator_uids for service in COORDINATOR_SERVICES}
        if devices:
            anchor = next(iter(devices))
            wanted |= {(anchor, service) for service in HOUSEHOLD_SERVICES}

        for key in list(self.subscriptions):
            if key not in wanted or not self.subscriptions[key].is_subscribed:
                self._remove(key)

        for uid, service in wanted - set(self.subscriptions):
            try:
                subscription = getattr(devices[uid], service).subscribe(requested_timeout=TIMEOUT, auto_renew=True)
                self.subscriptions[uid, service] = subscription
            except Exception:
                pass  # the speaker is unreachable; the next sync will try again

    def drain(self) -> list[Event]:
        """Collect everything the speakers have sent since the last call. Does not block."""
        events: list[Event] = []
        for (uid, service), subscription in list(self.subscriptions.items()):
            while True:
                try:
                    event = subscription.events.get_nowait()
                except queue.Empty:
                    break
                except Exception:
                    break
                events.append(Event(uid=uid, service=service, variables=event.variables))
        return events

    def stop(self) -> None:
        """Unsubscribe from everything, so that the speakers stop sending into the void."""
        for key in list(self.subscriptions):
            self._remove(key)
        try:
            event_listener.stop()
        except Exception:
            pass

    def _remove(self, key: tuple[str, str]) -> None:
        subscription = self.subscriptions.pop(key, None)
        if subscription is None:
            return
        try:
            subscription.unsubscribe()
        except Exception:
            pass
