from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import control_profile_dialog as dialog_module
from control_profile_dialog import ControlProfileDialog
from control_profiles import ACTION_ORDER, CUSTOM_SLOT_IDS, create_profile, default_seed


class Value:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class Widget:
    def __init__(self):
        self.options = {}

    def configure(self, **options):
        self.options.update(options)


def dialog_draft(*, problem=None, save_error=None):
    dialog = ControlProfileDialog.__new__(ControlProfileDialog)
    dialog.result = SimpleNamespace(problem=problem)
    dialog.store = SimpleNamespace(path=Path('fixture/control-profiles.json'))
    dialog.top = object()
    if save_error is not None:
        dialog.store.save_slot = Mock(side_effect=save_error)
    else:
        dialog.store.save_slot = Mock(side_effect=lambda slot_id, name, bindings:
            create_profile(slot_id, name, bindings))
    dialog.profiles = {}
    dialog.slot_labels = {slot: f'Profile {slot[-1]}' for slot in CUSTOM_SLOT_IDS}
    dialog.loaded_slot = 'slot-1'
    dialog.slot = Value('1 · Profile 1')
    dialog.name = Value('New layout')
    dialog.bindings = default_seed()
    dialog.binding_vars = {action: Value() for action in ACTION_ORDER}
    dialog.slot_combo = Widget()
    dialog.slot_status = Value()
    dialog.slot_status_label = Widget()
    dialog.capture_status = Value('Choose a key or press Capture.')
    dialog.on_saved = Mock()
    return dialog


def test_empty_slot_says_save_is_needed_before_it_can_be_assigned():
    dialog = dialog_draft()

    ControlProfileDialog._refresh_slot_status(dialog)

    assert dialog.slot_status.get() == 'Not saved yet. Save this profile to make it available in games.'
    assert dialog.slot_status_label.options['fg'] == '#9db7cc'


def test_saved_slot_shows_shared_next_launch_message():
    dialog = dialog_draft()
    dialog.profiles['slot-1'] = create_profile('slot-1', 'Arcade', default_seed())

    ControlProfileDialog._refresh_slot_status(dialog)

    assert dialog.slot_status.get() == 'Shared profile. Changes apply on the next launch.'


def test_read_problem_takes_priority_over_empty_slot_hint():
    dialog = dialog_draft(problem='invalid JSON')

    ControlProfileDialog._refresh_slot_status(dialog)

    assert f'Could not read {dialog.store.path}: invalid JSON' in dialog.slot_status.get()
    assert dialog.slot_status_label.options['fg'] == '#ffb6b6'


def test_successful_save_replaces_empty_slot_hint(monkeypatch):
    dialog = dialog_draft()
    ControlProfileDialog._refresh_slot_status(dialog)
    saved = create_profile('slot-1', 'New layout', default_seed())
    dialog.store.save_slot.return_value = saved

    ControlProfileDialog.save(dialog)

    assert dialog.profiles['slot-1'] == saved
    assert dialog.slot_status.get() == 'Shared profile. Changes apply on the next launch.'
    assert 'saved. Games using this profile' in dialog.capture_status.get()
    dialog.on_saved.assert_called_once_with('slot-1')


def test_failed_save_keeps_unsaved_hint_draft_and_no_success_callback(monkeypatch):
    dialog = dialog_draft(save_error=OSError('read only'))
    ControlProfileDialog._refresh_slot_status(dialog)
    original_bindings = dict(dialog.bindings)
    showerror = Mock()
    monkeypatch.setattr(dialog_module.messagebox, 'showerror', showerror)

    ControlProfileDialog.save(dialog)

    assert dialog.slot_status.get() == 'Not saved yet. Save this profile to make it available in games.'
    assert dialog.name.get() == 'New layout'
    assert dialog.bindings == original_bindings
    assert dialog.profiles == {}
    assert dialog.capture_status.get() == 'Choose a key or press Capture.'
    dialog.on_saved.assert_not_called()
    showerror.assert_called_once()
