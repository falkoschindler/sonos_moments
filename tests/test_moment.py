import pytest

from sonos_moments.model import Device, Group, Moment, Source, Track


def moment_with(source: Source) -> Moment:
    return Moment(uid='m', name='Moment', groups=[
        Group(coordinator_uid='a',
              members={'a': Device(uid='a', volume=20, mute=False)},
              state='PLAYING',
              source=source),
    ])


def test_a_favorite_survives_storage():
    moment = moment_with(Source(kind='favorite', title='radioeins', item_id='FV:2/63', uri='x-sonosapi-stream:9575'))
    assert Moment.from_dict(moment.to_dict()) == moment


def test_a_captured_queue_survives_storage():
    """The tracks are what makes a queue restorable, so they have to come back out of storage."""
    moment = moment_with(Source(kind='queue', title='An album',
                                tracks=[Track(uri='x-sonos-http:1.mp3', meta='<one/>'),
                                        Track(uri='x-sonos-http:2.mp3', meta='<two/>')],
                                track_number=2, track_position='0:01:30'))
    restored = Moment.from_dict(moment.to_dict())
    assert restored == moment
    assert restored.groups[0].source.tracks[1] == Track(uri='x-sonos-http:2.mp3', meta='<two/>')


def test_moments_from_before_sources_are_rejected():
    data = {'uid': 'm', 'name': 'Moment', 'groups': [{'coordinator_uid': 'a', 'members': {}, 'state': 'PLAYING',
                                                      'uri': 'x-sonosapi-stream:9575'}]}
    with pytest.raises(ValueError):
        Moment.from_dict(data)
