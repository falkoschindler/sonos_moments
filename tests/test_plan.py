import pytest

from sonos_moments.model import Device, Favorite, Group, GroupState, Moment, Source, SystemState, Track, plan

RADIOEINS = 'x-sonosapi-stream:tunein%3a9575?sid=303&flags=8224&sn=5'
RADIOEINS_PLAYING = 'x-sonosapi-stream:tunein%3A9575?sid=303&flags=8232&sn=5'  # other flags, other escaping
WDR5 = 'x-sonosapi-stream:s20301?sid=333&flags=8224&sn=8'

FAVORITES = [
    Favorite(title='radioeins', item_id='FV:2/63', uri=RADIOEINS, meta='<radioeins/>'),
    Favorite(title='WDR 5', item_id='FV:2/70', uri=WDR5, meta='<wdr5/>'),
]


def state_with(groups: dict[str, list[str]], *, volume: int = 20, mute: bool = False,
               transport: str = 'PLAYING', uri: str = RADIOEINS_PLAYING) -> SystemState:
    """Build a state from a mapping of coordinator to members."""
    state = SystemState()
    for member_uids in groups.values():
        for uid in member_uids:
            state.player(uid, name=uid)
            state.players[uid].volume = volume
            state.players[uid].mute = mute
    state.groups = [
        GroupState(coordinator_uid=coordinator_uid, member_uids=member_uids, transport_state=transport, uri=uri)
        for coordinator_uid, member_uids in groups.items()
    ]
    return state


def moment_with(groups: dict[str, list[str]], *, volume: int = 20, mute: bool = False,
                transport: str = 'PLAYING', source: Source | None = None) -> Moment:
    return Moment(uid='m', name='Moment', groups=[
        Group(coordinator_uid=coordinator_uid,
              members={uid: Device(uid=uid, volume=volume, mute=mute) for uid in member_uids},
              state=transport,
              source=source if source is not None else Source(kind='favorite', title='radioeins',
                                                              item_id='FV:2/63', uri=RADIOEINS))
        for coordinator_uid, member_uids in groups.items()
    ])


def test_nothing_to_do():
    result = plan(moment_with({'a': ['a', 'b']}), state_with({'a': ['a', 'b']}), FAVORITES)
    assert result.is_empty


def test_only_playback_differs():
    result = plan(moment_with({'a': ['a']}), state_with({'a': ['a']}, transport='STOPPED'), FAVORITES)
    assert result.transport == {'a': 'PLAYING'}
    assert not result.unjoin and not result.join and not result.sources


def test_same_grouping_with_another_coordinator_is_left_alone():
    """Who coordinates is invisible to the user and not worth rebuilding a group for."""
    result = plan(moment_with({'a': ['a', 'b']}), state_with({'b': ['b', 'a']}), FAVORITES)
    assert result.is_empty


def test_extra_member_leaves():
    result = plan(moment_with({'a': ['a']}), state_with({'a': ['a', 'b']}), FAVORITES)
    assert result.unjoin == ['b']
    assert not result.join


def test_member_is_fetched_from_another_group():
    result = plan(moment_with({'a': ['a', 'b']}), state_with({'a': ['a'], 'b': ['b']}), FAVORITES)
    assert result.join == [('b', 'a')]
    assert not result.unjoin


def test_coordinator_leaves_a_foreign_group():
    result = plan(moment_with({'a': ['a']}), state_with({'b': ['b', 'a']}), FAVORITES)
    assert result.unjoin == ['a']


def test_only_volume_differs():
    result = plan(moment_with({'a': ['a']}, volume=25), state_with({'a': ['a']}, volume=20), FAVORITES)
    assert result.volume == {'a': 25}
    assert not result.mute and not result.sources and not result.transport


def test_running_stream_counts_as_the_favorite_it_came_from():
    """The URI of the running stream carries other flags than the favorite, but is the same source."""
    result = plan(moment_with({'a': ['a']}), state_with({'a': ['a']}, uri=RADIOEINS_PLAYING), FAVORITES)
    assert not result.sources


def test_another_station_is_set_and_started():
    source = Source(kind='favorite', title='WDR 5', item_id='FV:2/70', uri=WDR5)
    result = plan(moment_with({'a': ['a']}, source=source), state_with({'a': ['a']}), FAVORITES)
    assert result.sources['a'] == Source(kind='uri', title='WDR 5', item_id='FV:2/70', uri=WDR5, meta='<wdr5/>')
    assert result.transport == {'a': 'PLAYING'}  # a freshly assigned source does not start by itself


def test_rebuilt_group_always_gets_its_source_again():
    result = plan(moment_with({'a': ['a', 'b']}), state_with({'a': ['a'], 'b': ['b']}), FAVORITES)
    assert result.sources['a'].uri == RADIOEINS
    assert result.transport == {'a': 'PLAYING'}


def test_vanished_favorite_is_reported():
    source = Source(kind='favorite', title='Gone', item_id='FV:2/99', uri='x-sonosapi-stream:gone')
    result = plan(moment_with({'a': ['a']}, source=source), state_with({'a': ['a']}), FAVORITES)
    assert result.unresolved == ['a']
    assert not result.sources


def test_a_moment_leaves_speakers_it_does_not_name_alone():
    state = state_with({'a': ['a'], 'c': ['c', 'd']})
    result = plan(moment_with({'a': ['a']}), state, FAVORITES)
    assert result.is_empty


def test_a_queue_is_always_filled_again():
    """A speaker playing from its queue reports the queue itself, which proves nothing about it."""
    source = Source(kind='queue', title='An album', tracks=[Track(uri='x-sonos-http:1.mp3', meta='<one/>')])
    result = plan(moment_with({'a': ['a']}, source=source),
                  state_with({'a': ['a']}, uri='x-rincon-queue:RINCON_a#0'), FAVORITES)
    assert result.sources['a'] is source
    assert result.transport == {'a': 'PLAYING'}


def test_an_empty_queue_is_reported():
    source = Source(kind='queue', title='An album')
    result = plan(moment_with({'a': ['a']}, source=source), state_with({'a': ['a']}), FAVORITES)
    assert result.unresolved == ['a']
    assert not result.sources


@pytest.mark.parametrize('kind', ['none', 'uri'])
def test_sourceless_moments(kind):
    source = Source(kind=kind, uri='' if kind == 'none' else RADIOEINS_PLAYING)
    result = plan(moment_with({'a': ['a']}, source=source), state_with({'a': ['a']}), FAVORITES)
    assert not result.sources
