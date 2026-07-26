from dataclasses import dataclass
from typing import Literal
from xml.sax.saxutils import escape

import soco
from soco.music_services import MusicService

SERVICE_NAME = 'TuneIn'
SERVICE_ID = 254  # the classic TuneIn service, which needs no account and therefore no serial number
SERVICE_DESC = 'SA_RINCON65031_'

# The service descriptor has to travel with the URI, otherwise the speaker does not know whom to
# ask for the stream. This is the same shape SoCo uses in ``play_uri`` for radio stations.
DIDL = ('<DIDL-Lite xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" '
        'xmlns:r="urn:schemas-rinconnetworks-com:metadata-1-0/" '
        'xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/">'
        '<item id="0fffffff{station_id}" parentID="0" restricted="true">'
        '<dc:title>{title}</dc:title>'
        '<upnp:class>object.item.audioItem.audioBroadcast</upnp:class>'
        f'<desc id="cdudn" nameSpace="urn:schemas-rinconnetworks-com:metadata-1-0/">{SERVICE_DESC}</desc>'
        '</item></DIDL-Lite>')


def station_uri(station_id: str) -> str:
    """Build the transport URI of a TuneIn station, e.g. ``s25111`` for radioeins.

    Deliberately without ``flags``: with ``flags=8224`` the speaker resolves the station against
    whichever service the household has linked and rewrites the URI to ``sid=303&sn=5``, which
    puts the account serial number back in -- exactly the thing that makes stored URIs rot.
    Without it the station stays on the anonymous TuneIn service and keeps working.

    What SoCo offers instead does not play: ``sonos_uri_from_id()`` returns a ``soco://`` pseudo
    URI and a searched station carries ``x-rincon-cpcontainer:``, both rejected with UPnP 714.
    """
    return f'x-sonosapi-stream:{station_id}?sid={SERVICE_ID}&sn=0'


def station_meta(station_id: str, title: str) -> str:
    return DIDL.format(station_id=station_id, title=escape(title))


@dataclass(kw_only=True, slots=True)
class Entry:
    """One line of the directory: either a folder to open or a station to play."""
    kind: Literal['folder', 'station']
    entry_id: str
    title: str

    @property
    def is_folder(self) -> bool:
        return self.kind == 'folder'


class Directory:
    """Browsing and searching TuneIn, so a station can be picked without the Sonos app.

    Every call blocks and talks to the service through a speaker; call from a thread.
    """

    def __init__(self) -> None:
        self._service: MusicService | None = None

    def _connect(self, device: soco.SoCo) -> MusicService:
        if self._service is None:
            # the service data is read from a speaker, so hand it one instead of letting SoCo
            # discover its own -- discovery in here would be a second, slower search
            self._service = MusicService(SERVICE_NAME, device=device)
        return self._service

    def browse(self, device: soco.SoCo, folder_id: str = '') -> list[Entry]:
        """List a folder of the directory, starting at the root."""
        return self._entries(self._connect(device).get_metadata(folder_id))

    def search(self, device: soco.SoCo, term: str) -> list[Entry]:
        """Search for stations. TuneIn also knows 'shows' and 'hosts', which we do not offer."""
        return self._entries(self._connect(device).search(category='stations', term=term))

    @staticmethod
    def _entries(items) -> list[Entry]:
        """Turn what the service returns into plain rows.

        Both browsing and searching hand back the same item types, and both need the raw service
        id from the metadata: the ``item_id`` carries a ``0fffffff`` prefix that the service does
        not accept back.
        """
        entries = []
        for item in items:
            entry_id = item.metadata.get('id')
            if not entry_id:
                continue
            kind = 'folder' if item.metadata.get('item_type') == 'container' else 'station'
            entries.append(Entry(kind=kind, entry_id=entry_id, title=item.title or entry_id))
        return entries
