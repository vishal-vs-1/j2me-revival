import json
from pathlib import Path

import pytest

import engine
import gpu_policy
from control_profiles import ControlProfileStore, default_seed, serialize_bindings


GAME_ID = "a" * 64


class FakeProcess:
    pass


@pytest.mark.parametrize("renderer", ["gpu", "cpu"])
@pytest.mark.parametrize("original", [False, True])
def test_custom_profile_is_a_single_jvm_argument_before_player_entry(tmp_path, monkeypatch, renderer, original):
    root = tmp_path / "app"
    (root / "build").mkdir(parents=True)
    (root / "build" / "jme-player.jar").touch()
    (root / "tools" / "gpu").mkdir(parents=True)
    (root / "tools" / "gpu" / "lwjgl-test.jar").touch()
    monkeypatch.setattr(engine, "ROOT", root)
    monkeypatch.setattr(engine, "locate_java", lambda *args: "java-cpu")
    monkeypatch.setattr(gpu_policy, "settings", lambda: {"render_gpu": "system"})
    monkeypatch.setattr(gpu_policy, "player_java", lambda mode: "java-gpu")
    monkeypatch.setattr(gpu_policy, "expected_device", lambda mode: {"name": "Test GPU"})

    captured = {}
    def popen(args, **kwargs):
        captured["args"] = args
        captured["cwd"] = kwargs["cwd"]
        return FakeProcess()
    monkeypatch.setattr(engine.subprocess, "Popen", popen)

    library_root = tmp_path / "library"
    rendered = tmp_path / "rendered"
    store = ControlProfileStore(tmp_path / "config" / "control-profiles.json", engine.atomic_json)
    profile = store.save_slot("slot-2", "WASD demo", default_seed())
    library = engine.Library(library_root, rendered, control_profiles=store)
    folder = rendered / GAME_ID
    (folder / "saves").mkdir(parents=True)
    (folder / "logs").mkdir()
    game = {
        "id": GAME_ID, "name": "Fixture", "status": "Ready", "renderer": renderer,
        "control_profile_id": "slot-2", "backend": "pixel", "width": 176,
        "height": 220, "render_scale": 4, "startup": {"note": "unchanged startup"},
    }
    library.prepare_startup = lambda current: tmp_path / "game.jar"

    process, log_path = library._launch(game, original=original)

    args = captured["args"]
    serialized = serialize_bindings(profile)
    prop = "-Djme.controlBindings=" + serialized
    assert process.__class__ is FakeProcess
    assert args.count(prop) == 1
    entry = "-cp" if renderer == "gpu" else "-jar"
    assert args.index(prop) < args.index(entry)
    assert args.count("-Djme.scale=1" if original else "-Djme.scale=4") == 1
    assert args[0] == ("java-gpu" if renderer == "gpu" else "java-cpu")
    assert captured["cwd"] == folder / "saves"
    log = log_path.read_text(encoding="utf-8")
    assert "Control profile: slot-2" in log
    assert "WASD demo" not in log


def test_default_launch_has_no_profile_property_and_stale_slot_logs_fallback(tmp_path, monkeypatch):
    root = tmp_path / "app"
    (root / "build").mkdir(parents=True)
    (root / "build" / "jme-player.jar").touch()
    monkeypatch.setattr(engine, "ROOT", root)
    monkeypatch.setattr(engine, "locate_java", lambda *args: "java-cpu")
    monkeypatch.setattr(gpu_policy, "settings", lambda: {"render_gpu": "system"})
    monkeypatch.setattr(gpu_policy, "player_java", lambda mode: "java-gpu")
    monkeypatch.setattr(gpu_policy, "expected_device", lambda mode: {"name": "Test GPU"})
    captured = {}
    def popen(args, **kwargs):
        captured["args"] = args
        return FakeProcess()
    monkeypatch.setattr(engine.subprocess, "Popen", popen)

    rendered = tmp_path / "rendered"
    store = ControlProfileStore(tmp_path / "config" / "control-profiles.json", engine.atomic_json)
    library = engine.Library(tmp_path / "library", rendered, control_profiles=store)
    folder = rendered / GAME_ID
    (folder / "saves").mkdir(parents=True)
    (folder / "logs").mkdir()
    game = {
        "id": GAME_ID, "name": "Fixture", "status": "Ready", "renderer": "cpu",
        "backend": "pixel", "width": 176, "height": 220, "startup": {"note": "unchanged startup"},
    }
    library.prepare_startup = lambda current: tmp_path / "game.jar"
    _, default_log = library._launch(game)
    assert not any(arg.startswith("-Djme.controlBindings=") for arg in captured["args"])
    assert "Control profile fallback" not in default_log.read_text(encoding="utf-8")

    game["control_profile_id"] = "slot-3"
    _, fallback_log = library._launch(game)
    assert not any(arg.startswith("-Djme.controlBindings=") for arg in captured["args"])
    assert "Control profile fallback: slot-3 -> default" in fallback_log.read_text(encoding="utf-8")
