import subprocess
from pathlib import Path

import pytest

from tools.patch_emulator import patch_control_profile_frontend


ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "freej2me-plus"
FRONTEND = "src/org/recompile/freej2me/FreeJ2ME.java"


def test_pinned_cpu_frontend_patch_is_focused_and_idempotent():
    original = subprocess.check_output(
        ["git", "-C", str(VENDOR), "show", "HEAD:" + FRONTEND],
        text=True,
        encoding="utf-8",
    )

    patched = patch_control_profile_frontend(original)

    assert patched.count("JAR Revival control profile input v1") == 1
    assert "AwtControlProfileInput.fromSystemProperty" in patched
    assert "pressMappedKey(mobikey, ignoreModifiers" in patched
    assert "releaseMappedKey(mobikey, true)" in patched
    assert "windowLostFocus" in patched
    assert patch_control_profile_frontend(patched) == patched


def test_cpu_frontend_patch_fails_clearly_when_upstream_anchor_changes():
    with pytest.raises(RuntimeError, match="expected one default press dispatcher anchor"):
        patch_control_profile_frontend("public class ChangedUpstream {}")
