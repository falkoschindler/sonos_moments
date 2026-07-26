from sonos_moments.model import Device, Group, Moment, Source
from sonos_moments.model.tunein import SERVICE_DESC


def moment_with(source: Source) -> Moment:
    return Moment(uid='m', name='Moment', groups=[
        Group(coordinator_uid='a',
              members={'a': Device(uid='a', volume=20, mute=False)},
              state='PLAYING',
              source=source),
    ])


def test_a_station_resolves_without_a_lookup():
    """A station id is stable, so nothing has to be looked up and nothing can be missing."""
    resolved = Source.station('s25111', 'radioeins').resolve([])
    assert resolved is not None
    assert resolved.kind == 'uri'
    assert resolved.title == 'radioeins'
    assert resolved.uri == 'x-sonosapi-stream:s25111?sid=254&sn=0'


def test_the_metadata_names_the_service():
    """Without the service descriptor the speaker does not know whom to ask for the stream."""
    resolved = Source.station('s25111', 'radioeins').resolve([])
    assert resolved is not None
    assert SERVICE_DESC in resolved.meta
    assert '<dc:title>radioeins</dc:title>' in resolved.meta
    assert 'object.item.audioItem.audioBroadcast' in resolved.meta


def test_a_station_title_is_escaped():
    resolved = Source.station('s1', 'Rock & Pop <live>').resolve([])
    assert resolved is not None
    assert 'Rock &amp; Pop &lt;live&gt;' in resolved.meta


def test_a_station_survives_storage():
    moment = moment_with(Source.station('s25111', 'radioeins'))
    assert Moment.from_dict(moment.to_dict()) == moment
