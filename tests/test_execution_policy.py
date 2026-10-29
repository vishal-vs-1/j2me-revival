import pytest
from execution_policy import java_execution_arguments


def test_existing_games_keep_normal_execution_and_metadata_is_unchanged():
    game={'id':'a'*64,'backend':'ai','renderer':'gpu','render_scale':4}
    before=dict(game)
    assert java_execution_arguments(game)==[] and game==before
    assert java_execution_arguments({'execution_mode':'normal'})==[]


def test_compatibility_is_explicit_and_independent_of_game_and_renderer():
    for renderer in ('cpu','gpu'):
        assert java_execution_arguments({'id':'any-game','renderer':renderer,
                                         'execution_mode':'compatible'})==['-XX:TieredStopAtLevel=1']
    assert java_execution_arguments({'execution_mode':'interpreted'})==['-XX:TieredStopAtLevel=1']


def test_invalid_mode_is_reported_instead_of_silently_changing_execution():
    with pytest.raises(ValueError):java_execution_arguments({'execution_mode':'unexpected'})
