"""Immutable control-profile values, validation, persistence and launch encoding."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import threading
from typing import Callable


DEFAULT_SLOT_ID = "default"
CUSTOM_SLOT_IDS = ("slot-1", "slot-2", "slot-3")
MAX_DOCUMENT_BYTES = 16 * 1024
MAX_BINDINGS_ARGUMENT = 1024

ACTION_ORDER = (
    "UP", "DOWN", "LEFT", "RIGHT", "FIRE", "SOFT_LEFT", "SOFT_RIGHT",
    "NUM_0", "NUM_1", "NUM_2", "NUM_3", "NUM_4", "NUM_5", "NUM_6",
    "NUM_7", "NUM_8", "NUM_9", "STAR", "HASH",
)
REQUIRED_ACTIONS = frozenset(ACTION_ORDER[:7])
DEFAULT_SEED = (
    ("UP", "ARROW_UP"), ("DOWN", "ARROW_DOWN"),
    ("LEFT", "ARROW_LEFT"), ("RIGHT", "ARROW_RIGHT"),
    ("FIRE", "ENTER"), ("SOFT_LEFT", "KEY_Q"), ("SOFT_RIGHT", "KEY_W"),
    ("NUM_0", "DIGIT_0"), ("NUM_1", "DIGIT_1"),
    ("NUM_2", "DIGIT_2"), ("NUM_3", "DIGIT_3"),
    ("NUM_4", "DIGIT_4"), ("NUM_5", "DIGIT_5"),
    ("NUM_6", "DIGIT_6"), ("NUM_7", "DIGIT_7"),
    ("NUM_8", "DIGIT_8"), ("NUM_9", "DIGIT_9"),
    ("STAR", "KEY_E"), ("HASH", "KEY_R"),
)

_LETTERS = frozenset(f"KEY_{letter}" for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
_DIGITS = frozenset(f"DIGIT_{digit}" for digit in "0123456789")
_NUMPAD = frozenset(f"NUMPAD_{digit}" for digit in "0123456789")
_ARROWS = frozenset(("ARROW_UP", "ARROW_DOWN", "ARROW_LEFT", "ARROW_RIGHT"))
SUPPORTED_KEYS = _LETTERS | _DIGITS | _NUMPAD | _ARROWS | frozenset(
    ("ENTER", "NUMPAD_ENTER", "SPACE")
)
_ACTION_SET = frozenset(ACTION_ORDER)
_DEFAULT_BINDINGS = dict(DEFAULT_SEED)


class ProfileValidationError(ValueError):
    """A profile value or persisted document violates the v1 contract."""


@dataclass(frozen=True)
class ControlProfile:
    """A saved profile with ordered, immutable action and key pairs."""

    slot_id: str
    name: str
    bindings: tuple[tuple[str, str | None], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "bindings", tuple(tuple(pair) for pair in self.bindings))


@dataclass(frozen=True)
class ProfileLoadResult:
    """A snapshot of available profiles, with a safe file-level read problem."""

    slots: tuple[ControlProfile, ...]
    problem: str | None = None

    def get(self, slot_id: str) -> ControlProfile | None:
        return next((profile for profile in self.slots if profile.slot_id == slot_id), None)


@dataclass(frozen=True)
class ProfileResolution:
    """Resolved custom bindings or the reason the request falls back to Default."""

    profile: ControlProfile | None
    reason: str | None = None


DEFAULT_PROFILE = ControlProfile(DEFAULT_SLOT_ID, "Default", ())
EMPTY_PROFILE_RESULT = ProfileLoadResult(())


def _validate_name(name: object) -> str:
    if not isinstance(name, str):
        raise ProfileValidationError("Profile name must be text.")
    normalized = name.strip()
    if not 1 <= len(normalized) <= 32:
        raise ProfileValidationError("Profile name must contain 1 to 32 characters.")
    if any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in normalized):
        raise ProfileValidationError("Profile name cannot contain control characters.")
    return normalized


def _validate_bindings(bindings: object) -> tuple[tuple[str, str | None], ...]:
    if not isinstance(bindings, dict):
        raise ProfileValidationError("Bindings must be an action-to-key object.")
    unknown_actions = set(bindings) - _ACTION_SET
    missing_actions = _ACTION_SET - set(bindings)
    if unknown_actions:
        raise ProfileValidationError(f"Unknown actions: {', '.join(sorted(map(str, unknown_actions)))}.")
    if missing_actions:
        raise ProfileValidationError(f"Missing actions: {', '.join(sorted(missing_actions))}.")

    used_keys: dict[str, str] = {}
    ordered: list[tuple[str, str | None]] = []
    for action in ACTION_ORDER:
        key = bindings[action]
        if key is None:
            if action in REQUIRED_ACTIONS:
                raise ProfileValidationError(f"{action} must have a key assigned.")
        elif not isinstance(key, str) or key not in SUPPORTED_KEYS:
            raise ProfileValidationError(f"{action} has an unsupported physical key.")
        else:
            previous_action = used_keys.get(key)
            if previous_action is not None:
                raise ProfileValidationError(f"{key} is already assigned to {previous_action}.")
            used_keys[key] = action
        ordered.append((action, key))
    return tuple(ordered)


def create_profile(slot_id: str, name: str, bindings: object) -> ControlProfile:
    if slot_id not in CUSTOM_SLOT_IDS:
        raise ProfileValidationError("Choose one of the three custom slots.")
    return ControlProfile(slot_id, _validate_name(name), _validate_bindings(bindings))


def default_seed() -> dict[str, str]:
    """Return a fresh editable copy of the standard custom-slot seed."""
    return dict(DEFAULT_SEED)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProfileValidationError(f"Duplicate JSON field {key!r}.")
        result[key] = value
    return result


def _decode_profile(slot_id: str, data: object) -> ControlProfile:
    if not isinstance(data, dict) or set(data) != {"name", "bindings"}:
        raise ProfileValidationError(f"{slot_id} must contain only name and bindings.")
    return create_profile(slot_id, data["name"], data["bindings"])


class ControlProfileStore:
    """Owns the small global profile document and its atomic write boundary."""

    def __init__(self, path: str | Path,
                 write_json: Callable[[Path, object], None]) -> None:
        self.path = Path(path)
        self._write_json = write_json
        self._lock = threading.RLock()

    def _read(self) -> ProfileLoadResult:
        try:
            with self.path.open("rb") as document:
                raw = document.read(MAX_DOCUMENT_BYTES + 1)
            if len(raw) > MAX_DOCUMENT_BYTES:
                raise ProfileValidationError("Control profile file exceeds 16 KiB.")
            data = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
            if not isinstance(data, dict) or set(data) != {"version", "slots"}:
                raise ProfileValidationError("Control profile file must contain only version and slots.")
            if type(data["version"]) is not int or data["version"] != 1:
                raise ProfileValidationError("Unsupported control profile file version.")
            slots_data = data["slots"]
            if not isinstance(slots_data, dict) or set(slots_data) - set(CUSTOM_SLOT_IDS):
                raise ProfileValidationError("Control profile slots must use the three fixed slot IDs.")
            slots = tuple(_decode_profile(slot_id, slots_data[slot_id])
                          for slot_id in CUSTOM_SLOT_IDS if slot_id in slots_data)
            return ProfileLoadResult(slots)
        except FileNotFoundError:
            return EMPTY_PROFILE_RESULT
        except (OSError, UnicodeError, json.JSONDecodeError, ProfileValidationError) as error:
            return ProfileLoadResult((), str(error))

    def load(self) -> ProfileLoadResult:
        with self._lock:
            return self._read()

    def save_slot(self, slot_id: str, name: str,
                  bindings: object) -> ControlProfile:
        # Validate the complete draft before reading or changing persisted state.
        profile = create_profile(slot_id, name, bindings)
        with self._lock:
            current = self._read()
            if current.problem:
                raise ProfileValidationError(
                    f"Cannot replace an unreadable profile file: {current.problem}"
                )
            slots = {item.slot_id: item for item in current.slots}
            slots[slot_id] = profile
            payload = {
                "version": 1,
                "slots": {
                    item.slot_id: {
                        "name": item.name,
                        "bindings": dict(item.bindings),
                    }
                    for item in (slots[key] for key in CUSTOM_SLOT_IDS if key in slots)
                },
            }
            self._write_json(self.path, payload)
        return profile


def resolve_selection(selection: object, result: ProfileLoadResult) -> ProfileResolution:
    """Resolve a game selection without letting stale IDs block a Default launch."""
    if selection is None or selection == DEFAULT_SLOT_ID:
        return ProfileResolution(None)
    if not isinstance(selection, str) or selection not in CUSTOM_SLOT_IDS:
        return ProfileResolution(None, "unknown control profile selection")
    if result.problem:
        return ProfileResolution(None, f"control profile file could not be read: {result.problem}")
    profile = result.get(selection)
    if profile is None:
        return ProfileResolution(None, f"selected control profile {selection} is no longer saved")
    return ProfileResolution(profile)


def serialize_bindings(profile: ControlProfile) -> str:
    """Build the bounded ASCII-only v1 JVM value without profile names or paths."""
    validated = create_profile(profile.slot_id, profile.name, dict(profile.bindings))
    value = "v1|" + "|".join(
        f"{action}={key if key is not None else 'NONE'}"
        for action, key in validated.bindings
    )
    encoded = value.encode("ascii")
    if len(encoded) > MAX_BINDINGS_ARGUMENT:
        raise ProfileValidationError("Control profile launch value exceeds 1024 ASCII characters.")
    return value
