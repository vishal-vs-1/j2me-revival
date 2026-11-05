"""Modal editor for the three shared keyboard control profiles."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from control_profiles import (
    ACTION_ORDER,
    CUSTOM_SLOT_IDS,
    REQUIRED_ACTIONS,
    SUPPORTED_KEYS,
    ProfileValidationError,
    create_profile,
    default_seed,
)
from ui_widgets import ScrollableFrame


def keysym_to_token(keysym: str) -> str | None:
    """Translate Tk's logical key names into the stable stored key tokens."""
    if len(keysym) == 1 and keysym.isascii() and keysym.isalpha():
        return f"KEY_{keysym.upper()}"
    if len(keysym) == 1 and keysym in "0123456789":
        return f"DIGIT_{keysym}"
    if len(keysym) == 4 and keysym.startswith("KP_") and keysym[-1] in "0123456789":
        return f"NUMPAD_{keysym[-1]}"
    return {
        "Up": "ARROW_UP",
        "Down": "ARROW_DOWN",
        "Left": "ARROW_LEFT",
        "Right": "ARROW_RIGHT",
        "Return": "ENTER",
        "KP_Enter": "NUMPAD_ENTER",
        "space": "SPACE",
    }.get(keysym)


def _key_label(token: str | None) -> str:
    return "Unbound" if token is None else token.replace("_", " ").title()


class ControlProfileDialog:
    def __init__(self, parent, store, on_saved: Callable[[str], None]) -> None:
        self.store = store
        self.on_saved = on_saved
        self.result = store.load()
        self.top = tk.Toplevel(parent)
        self.top.title("Settings")
        self.top.configure(bg="#121c29")
        self.top.transient(parent)
        self.top.resizable(True, True)
        self.top.geometry("560x700")
        self.top.minsize(500, 540)
        self.top.protocol("WM_DELETE_WINDOW", self.close)
        self.top.bind("<Escape>", self._escape)

        self.slot_labels = {slot: f"Profile {index}" for index, slot in enumerate(CUSTOM_SLOT_IDS, 1)}
        self.profiles = {profile.slot_id: profile for profile in self.result.slots}
        self.slot = tk.StringVar(value=CUSTOM_SLOT_IDS[0])
        self.name = tk.StringVar()
        self.slot_status = tk.StringVar()
        self.capture_status = tk.StringVar(value="Choose a key or press Capture.")
        self.capture_action: str | None = None
        self.capture_button = None
        self.capture_binding = None
        self.capture_focus_binding = None
        self.bindings: dict[str, str | None] = {}
        self.binding_vars: dict[str, tk.StringVar] = {}
        self.binding_combos: dict[str, ttk.Combobox] = {}
        self.baseline: tuple[str, tuple[tuple[str, str | None], ...]] | None = None
        self._build(parent)
        self._load_slot(CUSTOM_SLOT_IDS[0])
        self.top.grab_set()
        self.top.focus_set()

    def _build(self, parent) -> None:
        self.top.columnconfigure(0, weight=1)
        self.top.rowconfigure(2, weight=1)
        header = tk.Frame(self.top, bg="#121c29", padx=18, pady=14)
        header.grid(row=0, column=0, sticky="ew")
        tk.Label(header, text="Settings", bg="#121c29", fg="#eff5fc",
                 font=("Segoe UI", 16, "bold")).pack(anchor="w")
        tk.Label(header, text="Keyboard profiles", bg="#121c29", fg="#c4ffed",
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(5, 0))
        tk.Label(header,
                 text="Create up to three shared profiles. Choose a saved profile for each game in its Play tab.",
                 bg="#121c29", fg="#9db7cc", wraplength=500, justify="left").pack(anchor="w", pady=(4, 0))
        tk.Label(header, text="Editing a shared profile affects every game using it on its next launch.",
                 bg="#121c29", fg="#7994ac", wraplength=500, justify="left").pack(anchor="w", pady=(4, 0))

        slots = tk.Frame(self.top, bg="#121c29", padx=18)
        slots.grid(row=1, column=0, sticky="ew")
        slots.columnconfigure(0, weight=1)
        self.slot_combo = ttk.Combobox(slots, textvariable=self.slot, state="readonly", width=25)
        self.slot_combo.grid(row=0, column=0, sticky="ew")
        self.slot_combo.bind("<<ComboboxSelected>>", self._select_slot)
        self.slot_status_label = tk.Label(slots, textvariable=self.slot_status, bg="#121c29", fg="#9db7cc",
                                          justify="left", wraplength=490)
        self.slot_status_label.grid(row=1, column=0, sticky="w", pady=(6, 4))

        self.rows = ScrollableFrame(self.top, bg="#121c29")
        self.rows.grid(row=2, column=0, sticky="nsew", padx=18, pady=(8, 0))
        body = self.rows.content
        body.configure(padx=0, pady=4)
        body.columnconfigure(0, weight=1)
        for row, action in enumerate(ACTION_ORDER):
            panel = tk.Frame(body, bg="#192636", padx=9, pady=6)
            panel.grid(row=row, column=0, sticky="ew", pady=2)
            panel.columnconfigure(0, weight=1)
            required = " *" if action in REQUIRED_ACTIONS else ""
            tk.Label(panel, text=action.replace("_", " ").title() + required,
                     bg="#192636", fg="#dce7f5", anchor="w").grid(row=0, column=0, sticky="ew")
            variable = tk.StringVar()
            combo = ttk.Combobox(panel, textvariable=variable, state="readonly", width=19)
            combo.grid(row=0, column=1, padx=(8, 5))
            combo.bind("<<ComboboxSelected>>", lambda event, key=action: self._pick_key(key))
            capture = ttk.Button(panel, text="Capture")
            capture.configure(command=lambda key=action, button=capture: self._arm_capture(key, button))
            capture.grid(row=0, column=2)
            self.binding_vars[action] = variable
            self.binding_combos[action] = combo

        footer = tk.Frame(self.top, bg="#121c29", padx=18, pady=12)
        footer.grid(row=3, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self.capture_label = tk.Label(footer, textvariable=self.capture_status, bg="#121c29",
                                      fg="#9db7cc", anchor="w", justify="left", wraplength=360)
        self.capture_label.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        buttons = tk.Frame(footer, bg="#121c29")
        buttons.grid(row=0, column=1, rowspan=2, sticky="e", padx=(12, 0))
        ttk.Button(buttons, text="Cancel", command=self.close).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Save profile", command=self.save).pack(side="left")
        self.slot_combo.configure(values=self._slot_options())

    def _slot_options(self) -> tuple[str, ...]:
        return tuple(self._slot_label(slot) for slot in CUSTOM_SLOT_IDS)

    def _slot_label(self, slot_id: str) -> str:
        profile = self.profiles.get(slot_id)
        name = profile.name if profile else self.slot_labels[slot_id]
        return f"{slot_id[-1]} · {name}"

    def _slot_from_label(self, label: str) -> str | None:
        return next((slot for slot in CUSTOM_SLOT_IDS if label == self._slot_label(slot)), None)

    def _state(self) -> tuple[str, tuple[tuple[str, str | None], ...]]:
        return self.name.get(), tuple((action, self.bindings[action]) for action in ACTION_ORDER)

    def _is_dirty(self) -> bool:
        return self.baseline is not None and self._state() != self.baseline

    def _refresh_slot_status(self) -> None:
        if self.result.problem:
            text = f"Could not read {self.store.path}: {self.result.problem} Move the file aside to create profiles."
            color = "#ffb6b6"
        elif self.profiles.get(self.loaded_slot) is None:
            text = "Not saved yet. Save this profile to make it available in games."
            color = "#9db7cc"
        else:
            text = "Shared profile. Changes apply on the next launch."
            color = "#9db7cc"
        self.slot_status.set(text)
        self.slot_status_label.configure(fg=color)

    def _load_slot(self, slot_id: str) -> None:
        self._disarm_capture()
        self.loaded_slot = slot_id
        profile = self.profiles.get(slot_id)
        self.name.set(profile.name if profile else f"Profile {slot_id[-1]}")
        self.bindings = dict(profile.bindings) if profile else default_seed()
        self.baseline = self._state()
        self.slot.set(self._slot_label(slot_id))
        self._refresh_rows()
        self._refresh_slot_status()

    def _refresh_rows(self) -> None:
        used_keys = {key for key in self.bindings.values() if key is not None}
        for action in ACTION_ORDER:
            current = self.bindings[action]
            choices = [key for key in sorted(SUPPORTED_KEYS) if key == current or key not in used_keys]
            if action not in REQUIRED_ACTIONS:
                choices.insert(0, None)
            labels = tuple(_key_label(key) for key in choices)
            self.binding_combos[action].configure(values=labels)
            self.binding_vars[action].set(_key_label(current))

    def _change_binding(self, action: str, token: str | None) -> bool:
        if token is not None:
            conflict = next((other for other, key in self.bindings.items()
                             if key == token and other != action), None)
            if conflict:
                messagebox.showerror("Key already used", f"{_key_label(token)} is assigned to {conflict.replace('_', ' ').title()}.", parent=self.top)
                self._refresh_rows()
                return False
        if token is None and action in REQUIRED_ACTIONS:
            messagebox.showerror("Key required", "Directions, Fire and both soft keys need a binding.", parent=self.top)
            self._refresh_rows()
            return False
        self.bindings[action] = token
        self._refresh_rows()
        return True

    def _pick_key(self, action: str) -> None:
        label = self.binding_vars[action].get()
        token = None if label == "Unbound" else next(
            (key for key in SUPPORTED_KEYS if _key_label(key) == label), None)
        self._change_binding(action, token)

    def _select_slot(self, event=None) -> None:
        target = self._slot_from_label(self.slot.get())
        if target is None:
            return
        current = self.loaded_slot
        if target == current:
            return
        if self._is_dirty() and not messagebox.askyesno(
                "Discard changes?", "Discard the unsaved changes to this profile?", parent=self.top):
            self.slot.set(self._slot_label(current))
            return
        self.loaded_slot = target
        self._load_slot(target)

    def _arm_capture(self, action: str, button=None) -> None:
        self._disarm_capture()
        self.capture_action = action
        self.capture_button = button or self.top.focus_get()
        self.capture_status.set(f"Press one key for {action.replace('_', ' ').title()}. Escape cancels.")
        if self.capture_button is not None:
            self.capture_binding = self.capture_button.bind("<KeyPress>", self._captured_key, add="+")
            self.capture_focus_binding = self.capture_button.bind(
                "<FocusOut>", self._capture_focus_lost, add="+")
            self.capture_button.focus_set()

    def _disarm_capture(self) -> None:
        if self.capture_button is not None:
            if self.capture_binding:
                self.capture_button.unbind("<KeyPress>", self.capture_binding)
            if self.capture_focus_binding:
                self.capture_button.unbind("<FocusOut>", self.capture_focus_binding)
        self.capture_action = None
        self.capture_button = None
        self.capture_binding = None
        self.capture_focus_binding = None

    def _capture_focus_lost(self, event=None) -> None:
        if self.capture_action is not None:
            self._disarm_capture()
            self.capture_status.set("Capture cancelled because the button lost focus.")

    def _captured_key(self, event):
        action = self.capture_action
        if action is None:
            return "break"
        if event.keysym == "Escape":
            self._disarm_capture()
            self.capture_status.set("Capture cancelled. The old key is unchanged.")
            return "break"
        if event.state & (0x4 | 0x8 | 0x40):
            self.capture_status.set("Key chords are not supported. Press one key without Ctrl or Alt.")
            return "break"
        token = keysym_to_token(event.keysym)
        if token is None:
            self.capture_status.set("That key is not supported. Try a letter, number, arrow or Enter.")
            return "break"
        changed = self._change_binding(action, token)
        self._disarm_capture()
        if changed:
            self.capture_status.set(f"{action.replace('_', ' ').title()} is now {_key_label(token)}.")
        return "break"

    def _escape(self, event):
        if self.capture_action is not None:
            self._disarm_capture()
            self.capture_status.set("Capture cancelled. The old key is unchanged.")
            return "break"
        self.close()
        return "break"

    def save(self) -> None:
        slot_id = self._slot_from_label(self.slot.get())
        try:
            profile = create_profile(slot_id, self.name.get(), self.bindings)
            saved = self.store.save_slot(profile.slot_id, profile.name, dict(profile.bindings))
        except (OSError, ProfileValidationError, TypeError, ValueError) as error:
            messagebox.showerror("Could not save profile", str(error), parent=self.top)
            return
        self.profiles[saved.slot_id] = saved
        self.slot_combo.configure(values=self._slot_options())
        self.name.set(saved.name)
        self.loaded_slot = saved.slot_id
        self.baseline = self._state()
        self.slot.set(self._slot_label(saved.slot_id))
        self._refresh_slot_status()
        self.on_saved(saved.slot_id)
        self.capture_status.set(
            f"{saved.name} saved. Games using this profile will use the changes on their next launch.")

    def close(self) -> None:
        if self._is_dirty() and not messagebox.askyesno(
                "Discard changes?", "Discard the unsaved changes to this profile?", parent=self.top):
            return
        self._disarm_capture()
        self.top.grab_release()
        self.top.destroy()
