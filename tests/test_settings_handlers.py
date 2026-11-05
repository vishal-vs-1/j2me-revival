from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import app as app_module
from app import App
from control_profiles import DEFAULT_SLOT_ID


class Value:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class Combo:
    def __init__(self):
        self.options = {}

    def configure(self, **options):
        self.options.update(options)


class Executor:
    def __init__(self):
        self.calls = []

    def submit(self, callback):
        self.calls.append(callback)


def profile_app(game=None, label='1 · Arcade'):
    app = App.__new__(App)
    app.busy = False
    app.deleting_games = {}
    app.control_profile = Value(label)
    app.control_profile_choice_ids = {
        'Default': DEFAULT_SLOT_ID,
        '1 · Arcade': 'slot-1',
    }
    app._refresh_control_profile_controls = Mock()
    app.status = Value()
    app._delete_workers = Executor()
    app.messages = SimpleNamespace(put=Mock())
    app.library = SimpleNamespace(
        set_control_profile_id=Mock(),
        delete_game=Mock(),
    )
    app.game_if_selected = lambda: game
    return app


def test_profile_selection_persists_preference_without_scheduling_deletion():
    game = {'id': 'a' * 64, 'name': 'Fixture', 'render_scale': 4}
    app = profile_app(game)

    App.set_control_profile(app)

    app.library.set_control_profile_id.assert_called_once_with(game['id'], 'slot-1')
    assert game == {
        'id': 'a' * 64,
        'name': 'Fixture',
        'render_scale': 4,
        'control_profile_id': 'slot-1',
    }
    app.library.delete_game.assert_not_called()
    assert app._delete_workers.calls == []


def test_default_selection_removes_only_profile_preference():
    game = {'id': 'a' * 64, 'control_profile_id': 'slot-1', 'render_scale': 4}
    app = profile_app(game, 'Default')

    App.set_control_profile(app)

    app.library.set_control_profile_id.assert_called_once_with(game['id'], DEFAULT_SLOT_ID)
    assert game == {'id': 'a' * 64, 'render_scale': 4}
    app.library.delete_game.assert_not_called()
    assert app._delete_workers.calls == []


def test_failed_profile_write_keeps_game_and_never_deletes():
    game = {'id': 'a' * 64, 'control_profile_id': 'slot-2', 'render_scale': 4}
    app = profile_app(game)
    app.library.set_control_profile_id.side_effect = OSError('read only')

    App.set_control_profile(app)

    assert game['control_profile_id'] == 'slot-2'
    app.library.delete_game.assert_not_called()
    assert app._delete_workers.calls == []
    assert app.status.get() == 'Could not save control profile: read only'


@pytest.mark.parametrize('case', ['busy', 'deleting', 'no-game', 'unknown-label'])
def test_invalid_or_unavailable_selection_does_not_write_or_schedule(case):
    game = {'id': 'a' * 64, 'control_profile_id': 'slot-2'}
    app = profile_app(None if case == 'no-game' else game)
    if case == 'busy':
        app.busy = True
    elif case == 'deleting':
        app.deleting_games[game['id']] = game
    elif case == 'unknown-label':
        app.control_profile.set('Not a profile')

    App.set_control_profile(app)

    app.library.set_control_profile_id.assert_not_called()
    app.library.delete_game.assert_not_called()
    assert app._delete_workers.calls == []


def deletion_app(game):
    app = App.__new__(App)
    app.busy = False
    app.pending_imports = []
    app.players = {}
    app.deleting_games = {}
    app.root = object()
    app.status = Value()
    app._delete_workers = Executor()
    app.messages = SimpleNamespace(put=Mock())
    app.library = SimpleNamespace(delete_game=Mock())
    app.game = lambda: game
    app.refresh = Mock()
    app._update_row_actions = Mock()
    return app


def test_declined_delete_confirmation_submits_nothing(monkeypatch):
    game = {'id': 'a' * 64, 'name': 'Fixture'}
    app = deletion_app(game)
    ask = Mock(return_value=False)
    monkeypatch.setattr(app_module.messagebox, 'askyesno', ask)

    App.delete_game(app)

    ask.assert_called_once()
    assert app._delete_workers.calls == []
    assert app.deleting_games == {}
    app.library.delete_game.assert_not_called()


@pytest.mark.parametrize('failure', [None, OSError('locked')])
def test_confirmed_delete_submits_one_worker_and_reports_result(monkeypatch, failure):
    game = {'id': 'a' * 64, 'name': 'Fixture'}
    app = deletion_app(game)
    monkeypatch.setattr(app_module.messagebox, 'askyesno', Mock(return_value=True))
    if failure is not None:
        app.library.delete_game.side_effect = failure

    App.delete_game(app)

    assert len(app._delete_workers.calls) == 1
    assert game['id'] in app.deleting_games
    app.library.delete_game.assert_not_called()

    app._delete_workers.calls[0]()

    app.library.delete_game.assert_called_once_with(game['id'])
    expected = ('deleted', game) if failure is None else ('delete_error', (game, str(failure)))
    app.messages.put.assert_called_once_with(expected)


def test_repeated_delete_request_does_not_submit_another_worker(monkeypatch):
    game = {'id': 'a' * 64, 'name': 'Fixture'}
    app = deletion_app(game)
    monkeypatch.setattr(app_module.messagebox, 'askyesno', Mock(return_value=True))

    App.delete_game(app)
    App.delete_game(app)

    assert len(app._delete_workers.calls) == 1


class SettingsWindow:
    def __init__(self, exists=True):
        self.exists = exists
        self.deiconify = Mock()
        self.lift = Mock()

    def winfo_exists(self):
        return self.exists


class SettingsDialog:
    def __init__(self, exists=True):
        self.top = SettingsWindow(exists)


def test_settings_opens_without_a_selected_game_and_reuses_one_window(monkeypatch):
    store = object()
    app = App.__new__(App)
    app.root = object()
    app.library = SimpleNamespace(control_profiles=store)
    app.settings_dialog = None
    app.game_if_selected = Mock(side_effect=AssertionError('Settings must not depend on a game'))
    created = []

    def create_dialog(parent, actual_store, on_saved):
        dialog = SettingsDialog()
        created.append((dialog, parent, actual_store, on_saved))
        return dialog

    monkeypatch.setattr(app_module, 'ControlProfileDialog', create_dialog)

    App.open_settings(app)
    first, parent, actual_store, callback = created[0]
    assert parent is app.root and actual_store is store
    assert callback.__self__ is app and callback.__name__ == '_control_profiles_changed'

    App.open_settings(app)
    assert len(created) == 1
    first.top.deiconify.assert_called_once()
    first.top.lift.assert_called_once()
    app.game_if_selected.assert_not_called()

    first.top.exists = False
    App.open_settings(app)
    assert len(created) == 2
    assert app.settings_dialog is created[1][0]


@pytest.mark.parametrize(
    ('game_id', 'saved_slots', 'expected_label', 'expected_info'),
    [
        ('default', [], 'Default', 'Create shared profiles in Settings.'),
        ('default', [('slot-1', 'New layout')], 'Default',
         'Profiles are managed in Settings. Choice applies next launch.'),
        ('slot-2', [('slot-2', 'Rally renamed')], '2 · Rally renamed',
         'Profiles are managed in Settings. Choice applies next launch.'),
    ],
)
def test_shared_profile_refresh_preserves_each_games_choice_and_only_updates_labels(
        game_id, saved_slots, expected_label, expected_info):
    profiles = tuple(SimpleNamespace(slot_id=slot_id, name=name) for slot_id, name in saved_slots)
    store = SimpleNamespace(load=Mock(return_value=SimpleNamespace(slots=profiles, problem=None)))
    game = {'id': 'a' * 64, 'control_profile_id': game_id, 'render_scale': 4}
    app = App.__new__(App)
    app.library = SimpleNamespace(
        control_profiles=store,
        set_control_profile_id=Mock(),
        save=Mock(),
        delete_game=Mock(),
        launch=Mock(),
    )
    app.control_profile_combo = Combo()
    app.control_profile = Value()
    app.control_profile_info = Value()
    app.busy = False
    app.deleting_games = {}
    app.game_if_selected = Mock(return_value=game)

    App._control_profiles_changed(app, saved_slots[0][0] if saved_slots else 'slot-1')

    assert app.control_profile.get() == expected_label
    assert app.control_profile_info.get() == expected_info
    assert game['control_profile_id'] == game_id
    assert game['render_scale'] == 4
    app.library.set_control_profile_id.assert_not_called()
    app.library.save.assert_not_called()
    app.library.delete_game.assert_not_called()
    app.library.launch.assert_not_called()
    assert app.control_profile_combo.options['values'] == tuple(app.control_profile_choice_ids)
