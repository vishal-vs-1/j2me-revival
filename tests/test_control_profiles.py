import json
from pathlib import Path

import pytest

from control_profiles import (
    ACTION_ORDER,
    CUSTOM_SLOT_IDS,
    DEFAULT_SEED,
    DEFAULT_PROFILE,
    ControlProfile,
    MAX_DOCUMENT_BYTES,
    ControlProfileStore,
    ProfileValidationError,
    create_profile,
    default_seed,
    resolve_selection,
    serialize_bindings,
)
from control_profile_dialog import keysym_to_token


def text_json_writer(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")


def new_store(tmp_path, writer=text_json_writer):
    return ControlProfileStore(tmp_path / "config" / "control-profiles.json", writer)


def profile(slot_id="slot-1", name="WASD"):
    return create_profile(slot_id, name, default_seed())


def test_missing_file_starts_with_empty_fixed_slots_and_default_is_immutable(tmp_path):
    store = new_store(tmp_path)

    result = store.load()

    assert result.slots == ()
    assert result.problem is None
    assert CUSTOM_SLOT_IDS == ("slot-1", "slot-2", "slot-3")
    assert DEFAULT_PROFILE.slot_id == "default"
    assert DEFAULT_PROFILE.name == "Default"
    assert DEFAULT_PROFILE.bindings == ()
    with pytest.raises(AttributeError):
        DEFAULT_PROFILE.name = "Changed"

    editable_pairs = [["UP", "KEY_W"]]
    snapshot = ControlProfile("default", "Default", editable_pairs)
    editable_pairs[0][1] = "KEY_S"
    assert snapshot.bindings == (("UP", "KEY_W"),)


def test_save_and_reload_three_slots_in_fixed_order_and_keep_unicode(tmp_path):
    store = new_store(tmp_path)
    store.save_slot("slot-3", "日本語 🎮", default_seed())
    store.save_slot("slot-1", "WASD", default_seed())
    store.save_slot("slot-2", "D-pad 2", default_seed())

    result = store.load()

    assert [item.slot_id for item in result.slots] == list(CUSTOM_SLOT_IDS)
    assert result.get("slot-3").name == "日本語 🎮"
    assert dict(result.get("slot-1").bindings) == default_seed()


def test_replacing_slot_preserves_other_slots(tmp_path):
    store = new_store(tmp_path)
    store.save_slot("slot-1", "One", default_seed())
    store.save_slot("slot-2", "Two", default_seed())

    store.save_slot("slot-1", "Renamed", default_seed())

    result = store.load()
    assert [(item.slot_id, item.name) for item in result.slots] == [
        ("slot-1", "Renamed"), ("slot-2", "Two")
    ]


@pytest.mark.parametrize("bad_name", ["", "   ", "x" * 33, "bad\nname"])
def test_rejects_invalid_profile_names(tmp_path, bad_name):
    with pytest.raises(ProfileValidationError):
        create_profile("slot-1", bad_name, default_seed())


def test_rejects_duplicate_keys_missing_actions_and_missing_required_keys():
    duplicate = default_seed()
    duplicate["RIGHT"] = duplicate["LEFT"]
    with pytest.raises(ProfileValidationError, match="already assigned"):
        create_profile("slot-1", "Bad", duplicate)

    missing = default_seed()
    del missing["STAR"]
    with pytest.raises(ProfileValidationError, match="Missing actions"):
        create_profile("slot-1", "Bad", missing)

    unbound_required = default_seed()
    unbound_required["FIRE"] = None
    with pytest.raises(ProfileValidationError, match="FIRE must"):
        create_profile("slot-1", "Bad", unbound_required)


def test_optional_actions_can_be_unbound_and_saved_as_null(tmp_path):
    bindings = default_seed()
    bindings["NUM_5"] = None

    saved = new_store(tmp_path).save_slot("slot-1", "No five", bindings)

    assert dict(saved.bindings)["NUM_5"] is None
    document = json.loads((tmp_path / "config" / "control-profiles.json").read_text())
    assert document["slots"]["slot-1"]["bindings"]["NUM_5"] is None


@pytest.mark.parametrize("document", [
    '{"version":1,"version":1,"slots":{}}',
    '{"version":true,"slots":{}}',
    '{"version":2,"slots":{}}',
    '{"version":1,"slots":{"slot-4":{}}}',
    '{"version":1,"slots":{"slot-1":{"name":"A","bindings":{},"extra":1}}}',
    '{"version":1,"slots":{"slot-1":{"name":"A","bindings":{"UP":"KEY_W","UP":"KEY_A"}}}}',
])
def test_invalid_documents_fail_closed_and_are_not_overwritten(tmp_path, document):
    path = tmp_path / "control-profiles.json"
    path.write_text(document, encoding="utf-8")
    before = path.read_bytes()
    store = ControlProfileStore(path, text_json_writer)

    result = store.load()

    assert result.slots == ()
    assert result.problem
    with pytest.raises(ProfileValidationError, match="Cannot replace"):
        store.save_slot("slot-1", "Replacement", default_seed())
    assert path.read_bytes() == before


def test_oversized_file_is_reported_without_partial_profile(tmp_path):
    path = tmp_path / "control-profiles.json"
    path.write_bytes(b" " * (MAX_DOCUMENT_BYTES + 1))

    result = ControlProfileStore(path, text_json_writer).load()

    assert result.slots == ()
    assert "exceeds 16 KiB" in result.problem


def test_ascii_serializer_is_stable_complete_and_keeps_default_out_of_wire():
    encoded = serialize_bindings(profile())

    assert encoded.isascii()
    assert encoded == "v1|" + "|".join(
        f"{action}={dict(DEFAULT_SEED)[action]}" for action in ACTION_ORDER
    )
    assert serialize_bindings(create_profile(
        "slot-2", "Optional keypad", {**default_seed(), "NUM_5": None}
    )).split("|")[13] == "NUM_5=NONE"
    with pytest.raises(ProfileValidationError):
        serialize_bindings(DEFAULT_PROFILE)


def test_python_wire_matches_the_java_shared_fixture():
    fixture = Path(__file__).parent / "fixtures" / "control_profile_wire.txt"

    assert serialize_bindings(profile()) == fixture.read_text(encoding="ascii").strip()


def test_selection_falls_back_with_a_reason_when_custom_slot_is_missing(tmp_path):
    result = new_store(tmp_path).load()

    assert resolve_selection(None, result).profile is None
    assert resolve_selection("default", result).reason is None
    missing = resolve_selection("slot-2", result)
    assert missing.profile is None
    assert "no longer saved" in missing.reason


@pytest.mark.parametrize(("keysym", "expected"), [
    ("a", "KEY_A"), ("Z", "KEY_Z"), ("5", "DIGIT_5"),
    ("KP_5", "NUMPAD_5"), ("Up", "ARROW_UP"),
    ("Return", "ENTER"), ("KP_Enter", "NUMPAD_ENTER"),
    ("space", "SPACE"), ("Escape", None), ("F11", None),
])
def test_tk_key_names_map_only_supported_physical_keys(keysym, expected):
    assert keysym_to_token(keysym) == expected
