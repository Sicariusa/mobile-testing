"""Validate read_apk_metadata against a REAL apk with a REAL aapt.

The uiautomator2 package ships its ATX agent APK as a data asset, so this test
is portable: anywhere aapt (or aapt2) and uiautomator2 are installed, it proves
the aapt integration + parsing end to end. It skips cleanly when either tool is
absent (e.g. a core-only environment).
"""
from __future__ import annotations

import os
import shutil

import pytest

from engine.device import read_apk_metadata


def _bundled_apk() -> str | None:
    try:
        import uiautomator2
    except Exception:
        return None
    path = os.path.join(os.path.dirname(uiautomator2.__file__),
                        "assets", "app-uiautomator.apk")
    return path if os.path.exists(path) else None


@pytest.mark.skipif(shutil.which("aapt") is None and shutil.which("aapt2") is None,
                    reason="aapt/aapt2 not installed (live-run tool)")
def test_read_apk_metadata_real_apk():
    apk = _bundled_apk()
    if apk is None:
        pytest.skip("no bundled uiautomator2 APK available")
    meta = read_apk_metadata(apk)
    assert meta["package"] == "com.github.uiautomator"
    assert meta["launch_activity"] == "com.github.uiautomator.MainActivity"
