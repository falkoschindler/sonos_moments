from dataclasses import dataclass, field
from typing import Literal, Self
from urllib.parse import unquote

import soco

from .tunein import station_meta, station_uri

CONTAINER_PREFIXES = ('x-rincon-cpcontainer:', 'x-rincon-playlist:')
QUEUE_PREFIX = 'x-rincon-queue:'  # a speaker playing its own queue, which says nothing about the contents


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
class Track:
    """One entry of a queue: URI and metadata are all a speaker needs to take it back."""
    uri: str
    meta: str


@dataclass(kw_only=True, slots=True)
class Source:
    """A reference to something playable, resolved only when it is actually played.

    Storing the transport URI of whatever happened to be playing does not survive: for radio it
    is often an already resolved CDN address with an expiring token, and even the stable service
    URIs carry an account serial number that changes when a service is re-linked or migrated.
    A favorite, on the other hand, is kept working by Sonos itself.
    """
    kind: Literal['favorite', 'station', 'uri', 'queue', 'none']
    title: str = ''
    item_id: str = ''  # of the favorite, or the id of the TuneIn station
    uri: str = ''
    meta: str = ''
    tracks: list[Track] = field(default_factory=list)
    track_number: int = 1  # which entry of the queue was playing, counted from 1
    track_position: str = ''  # how far into that entry, as 'H:MM:SS'

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

    @classmethod
    def capture_queue(cls, tracks: list[Track], title: str, track_number: int, track_position: str) -> Self:
        """Describe a queue by its contents.

        A speaker playing from its queue reports ``x-rincon-queue:<uid>#0`` as its transport URI,
        which is a pointer to itself: restoring it would play whatever happens to be in the queue
        at that later point in time, not the album or playlist that was playing when we looked.
        """
        if not tracks:
            return cls(kind='none')
        return cls(kind='queue', title=title, tracks=tracks,
                   track_number=track_number, track_position=track_position)

    @classmethod
    def station(cls, station_id: str, title: str) -> Self:
        """Point at a TuneIn station, which is as durable as a favorite and needs no lookup."""
        return cls(kind='station', title=title, item_id=station_id)

    def resolve(self, favorites: list[Favorite]) -> Self | None:
        """Return the source to play, or None if it cannot be found any more.

        A favorite is looked up freshly every time, because surviving a re-linked music service is
        the entire reason for storing one.
        """
        if self.kind == 'station':
            # nothing to look up: the station id is stable and the URI is built from it
            return type(self)(kind='uri', title=self.title, item_id=self.item_id,
                              uri=station_uri(self.item_id), meta=station_meta(self.item_id, self.title))
        if self.kind == 'favorite':
            favorite = next((favorite for favorite in favorites if favorite.item_id == self.item_id), None) \
                or next((favorite for favorite in favorites if favorite.title == self.title), None)
            if favorite is None:
                return None
            return type(self)(kind='uri', title=favorite.title, item_id=favorite.item_id,
                              uri=favorite.uri, meta=favorite.meta)
        if self.kind == 'uri':
            return self if self.uri else None
        if self.kind == 'queue':
            return self if self.tracks else None
        return None

    @property
    def description(self) -> str:
        return self.title or self.uri

    def apply(self, device: soco.SoCo) -> None:
        """Make this source the current one, without starting playback.

        Blocking; call from a thread. Playing is left to the caller because a speaker needs a
        moment before it accepts a play command for a source it has just been handed.
        """
        if self.kind == 'queue':
            self._fill_queue(device)
        elif self.uri.startswith(CONTAINER_PREFIXES):
            # containers such as playlists have to go through the queue, streams can be handed
            # to the transport directly
            device.avTransport.RemoveAllTracksFromQueue([('InstanceID', 0)])
            device.avTransport.AddURIToQueue([('InstanceID', 0),
                                              ('EnqueuedURI', self.uri),
                                              ('EnqueuedURIMetaData', self.meta),
                                              ('DesiredFirstTrackNumberEnqueued', 0),
                                              ('EnqueueAsNext', 0)])
            device.play_from_queue(0, start=False)
        else:
            device.avTransport.SetAVTransportURI([('InstanceID', 0),
                                                  ('CurrentURI', self.uri),
                                                  ('CurrentURIMetaData', self.meta)])

    def _fill_queue(self, device: soco.SoCo) -> None:
        """Put the stored tracks back into the queue and pick up where the capture left off.

        One request per track, like ``SoCo.add_to_queue``, but with the metadata we captured, so
        titles and artwork survive. Batching exists as ``AddMultipleURIsToQueue``, which joins the
        metadata of several tracks with spaces -- not something to rely on untested.
        """
        device.avTransport.RemoveAllTracksFromQueue([('InstanceID', 0)])
        for track in self.tracks:
            device.avTransport.AddURIToQueue([('InstanceID', 0),
                                              ('EnqueuedURI', track.uri),
                                              ('EnqueuedURIMetaData', track.meta),
                                              ('DesiredFirstTrackNumberEnqueued', 0),
                                              ('EnqueueAsNext', 0)])
        device.play_from_queue(max(0, self.track_number - 1), start=False)
        if self.track_position:
            try:
                device.seek(self.track_position)
            except soco.exceptions.SoCoUPnPException:
                pass  # not every source can be seeked, and the track itself matters more
