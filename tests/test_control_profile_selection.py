import json

import pytest

from control_profiles import ControlProfileStore, ProfileValidationError, default_seed
from engine import Library, atomic_json


GAME_ID = "a" * 64


def ready_library(tmp_path):
    library_root = tmp_path / "library"
    rendered_root = tmp_path / "rendered"
    profile_store = ControlProfileStore(tmp_path / "config" / "control-profiles.json", atomic_json)
    profile_store.save_slot("slot-2", "WASD", default_seed())
    library = Library(library_root, rendered_root, control_profiles=profile_store)
    game_file = rendered_root / GAME_ID / "game.json"
    game_file.parent.mkdir(parents=True)
    game_file.write_text(json.dumps({
        "id": GAME_ID,
        "name": "Fixture game",
        "render_scale": 4,
        "asset_work": {"READY": 4},
    }), encoding="utf-8")
    return library, game_file


def test_profile_selection_updates_only_game_metadata_and_default_removes_it(tmp_path):
    library, game_file = ready_library(tmp_path)

    library.set_control_profile_id(GAME_ID, "slot-2")
    selected = json.loads(game_file.read_text(encoding="utf-8"))
    assert selected["control_profile_id"] == "slot-2"
    assert selected["render_scale"] == 4
    assert selected["asset_work"] == {"READY": 4}

    library.set_control_profile_id(GAME_ID, "default")
    reset = json.loads(game_file.read_text(encoding="utf-8"))
    assert "control_profile_id" not in reset
    assert reset["render_scale"] == 4


def test_profile_selection_rejects_unsaved_slot_and_missing_game(tmp_path):
    library, game_file = ready_library(tmp_path)

    with pytest.raises(ProfileValidationError, match="no longer saved"):
        library.set_control_profile_id(GAME_ID, "slot-1")
    with pytest.raises(FileNotFoundError):
        library.set_control_profile_id("b" * 64, "default")

    assert "control_profile_id" not in json.loads(game_file.read_text(encoding="utf-8"))


def test_default_can_be_selected_when_global_profile_file_is_corrupt(tmp_path):
    library, game_file = ready_library(tmp_path)
    library.control_profiles.path.write_text("broken", encoding="utf-8")

    library.set_control_profile_id(GAME_ID, "default")

    assert "control_profile_id" not in json.loads(game_file.read_text(encoding="utf-8"))


def test_games_keep_independent_profile_selections(tmp_path):
    library, first_file = ready_library(tmp_path)
    second_id = "b" * 64
    second_file = first_file.parent.parent / second_id / "game.json"
    second_file.parent.mkdir()
    second_file.write_text(json.dumps({"id": second_id, "name": "Second"}), encoding="utf-8")

    library.set_control_profile_id(GAME_ID, "slot-2")
    library.set_control_profile_id(second_id, "default")

    assert json.loads(first_file.read_text(encoding="utf-8"))["control_profile_id"] == "slot-2"
    assert "control_profile_id" not in json.loads(second_file.read_text(encoding="utf-8"))
