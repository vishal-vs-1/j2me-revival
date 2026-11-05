import hashlib
from pathlib import Path

import pytest

from tools.patch_emulator import patch_control_profile_frontend


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_FIXTURE = ROOT / "tests" / "fixtures" / "freej2me-plus" / "FreeJ2ME.java.txt"
FRONTEND_SHA256 = "3807282d28dcf45fefe94685a42ce7bce852856528b056c4dd3ef2d1cefa1d2f"


def test_pinned_cpu_frontend_patch_is_focused_and_idempotent():
    # Keep the pinned-source check independent of an optional local emulator checkout.
    original = FRONTEND_FIXTURE.read_text(encoding="utf-8")
    assert hashlib.sha256(original.encode("utf-8")).hexdigest() == FRONTEND_SHA256

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
