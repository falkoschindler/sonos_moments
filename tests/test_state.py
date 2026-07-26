from sonos_moments.model import GroupState, SystemState

STALE_AFTER = 120.0
NOW = 1000.0


def state_with(*uids: str) -> SystemState:
    state = SystemState()
    for uid in uids:
        state.player(uid, name=uid.title())
    return state


def test_a_speaker_starts_out_as_not_reachable():
    """Nothing has answered yet, so there is nothing to show but the name."""
    state = state_with('a')
    assert not state.players['a'].online
    assert state.forget_silent(NOW, STALE_AFTER) is False  # already offline, no news


def test_being_seen_brings_a_speaker_back():
    state = state_with('a')
    assert state.seen('a', NOW) is True  # news, the UI has to be told
    assert state.players['a'].online
    assert state.seen('a', NOW + 1) is False  # still here, nothing to report


def test_silence_greys_a_speaker_out():
    state = state_with('a')
    state.seen('a', NOW)
    assert state.forget_silent(NOW + STALE_AFTER, STALE_AFTER) is False
    assert state.forget_silent(NOW + STALE_AFTER + 1, STALE_AFTER) is True
    assert not state.players['a'].online


def test_an_event_keeps_a_speaker_alive_through_a_failed_read():
    """A speaker busy pushing events must not be greyed out because one read timed out."""
    state = state_with('a')
    state.seen('a', NOW)
    state.seen('a', NOW + STALE_AFTER)  # an event arrived in between
    assert state.forget_silent(NOW + STALE_AFTER + 1, STALE_AFTER) is False
    assert state.players['a'].online


def test_a_lost_speaker_is_greyed_out_right_away():
    state = state_with('a')
    state.seen('a', NOW)
    assert state.lost('a') is True
    assert state.lost('a') is False  # already gone, no news
    assert not state.players['a'].online


def test_absent_speakers_are_the_ones_without_a_group():
    state = state_with('a', 'b', 'c')
    state.seen('a', NOW)
    state.seen('b', NOW)
    state.groups = [GroupState(coordinator_uid='a', member_uids=['a', 'b'])]
    assert [player.uid for player in state.absent_players] == ['c']


def test_an_unreachable_member_of_a_group_is_not_listed_twice():
    """It keeps its row in the group, so it must not show up among the absent ones as well."""
    state = state_with('a', 'b')
    state.groups = [GroupState(coordinator_uid='a', member_uids=['a', 'b'])]
    assert state.absent_players == []
