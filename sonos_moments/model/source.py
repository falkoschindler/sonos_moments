from dataclasses import dataclass
from typing import Literal, Self
from urllib.parse import unquote

import soco

CONTAINER_PREFIXES = ('x-rincon-cpcontainer:', 'x-rincon-playlist:')


def match_key(uri: str) -> str:
    """Reduce a URI to the part that identifies the source.

    The same station looks slightly different depending on where the URI comes from: a favorite
    carries other ``flags`` than the running stream and escapes its characters differently. What
    stays the same is the service id and the item behind it.
    """
    base, _, query = uri.partition('?')
    parameters = dict(parameter.split('=', 1) for parameter in query.split('&') if '=' in parameter)
    return f'{unquote(base).lower()}|{parameters.get("sid", "")}'


@dataclass(kw_only=True, slots=True)
class Favorite:
    """A Sonos favorite, as maintained by Sonos itself."""
    title: str
    item_id: str
    uri: str
    meta: str

    @classmethod
    def read(cls, device: soco.SoCo) -> list[Self]:
        """Read the favorites of the household. Blocking; call from a thread."""
        favorites = []
        for favorite in device.music_library.get_sonos_favorites(max_items=200):
            resources = getattr(favorite, 'resources', None)
            if not resources:
                continue  # promotional tiles without anything playable behind them
            favorites.append(cls(title=favorite.title,
                                 item_id=favorite.item_id,
                                 uri=resources[0].uri,
                                 meta=favorite.resource_meta_data or ''))
        return sorted(favorites, key=lambda favorite: favorite.title.lower())


@dataclass(kw_only=True, slots=True)
class Source:
    """A reference to something playable, resolved only when it is actually played.

    Storing the transport URI of whatever happened to be playing does not survive: for radio it
    is often an already resolved CDN address with an expiring token, and even the stable service
    URIs carry an account serial number that changes when a service is re-linked or migrated.
    A favorite, on the other hand, is kept working by Sonos itself.
    """
    kind: Literal['favorite', 'uri', 'none']
    title: str = ''
    item_id: str = ''
    uri: str = ''
    meta: str = ''

    @classmethod
    def capture(cls, uri: str, meta: str, title: str, favorites: list[Favorite]) -> Self:
        """Describe what is playing, preferring a favorite over a raw URI."""
        if not uri:
            return cls(kind='none')
        key = match_key(uri)
        favorite = next((favorite for favorite in favorites if match_key(favorite.uri) == key), None)
        if favorite is not None:
            return cls(kind='favorite', title=favorite.title, item_id=favorite.item_id, uri=uri, meta=meta)
        return cls(kind='uri', title=title, uri=uri, meta=meta)

    def resolve(self, favorites: list[Favorite]) -> tuple[str, str] | None:
        """Return URI and metadata to play, or None if the source is gone."""
        if self.kind == 'none':
            return None
        if self.kind == 'favorite':
            favorite = next((favorite for favorite in favorites if favorite.item_id == self.item_id), None) \
                or next((favorite for favorite in favorites if favorite.title == self.title), None)
            return (favorite.uri, favorite.meta) if favorite is not None else None
        return (self.uri, self.meta) if self.uri else None

    @property
    def description(self) -> str:
        return self.title or self.uri

    @staticmethod
    def select(device: soco.SoCo, uri: str, meta: str) -> None:
        """Make a resolved source the current one, without starting playback yet.

        Blocking; call from a thread. Containers such as playlists have to go through the queue,
        streams can be handed to the transport directly. Playing is left to the caller because a
        speaker needs a moment before it accepts a play command for a fresh stream.
        """
        if uri.startswith(CONTAINER_PREFIXES):
            device.avTransport.RemoveAllTracksFromQueue([('InstanceID', 0)])
            device.avTransport.AddURIToQueue([('InstanceID', 0),
                                              ('EnqueuedURI', uri),
                                              ('EnqueuedURIMetaData', meta),
                                              ('DesiredFirstTrackNumberEnqueued', 0),
                                              ('EnqueueAsNext', 0)])
            device.play_from_queue(0)
        else:
            device.avTransport.SetAVTransportURI([('InstanceID', 0),
                                                  ('CurrentURI', uri),
                                                  ('CurrentURIMetaData', meta)])
