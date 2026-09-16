"""Incremental logcat (audit P2): each step scans only newly produced lines."""
from __future__ import annotations

from engine.device import AndroidDevice


class _ScriptedLogcat(AndroidDevice):
    """AndroidDevice with a scripted buffer instead of a live adb connection."""

    def __init__(self, buffer: str):
        self._buf = buffer
        self._logcat_seen = 0

    def logcat_since_launch(self) -> str:
        return self._buf


def test_logcat_new_returns_only_new_lines():
    d = _ScriptedLogcat("line1\nline2\n")
    first = d.logcat_new()
    assert first.splitlines() == ["line1", "line2"]
    # nothing new -> empty
    assert d.logcat_new() == ""
    # buffer grows -> only the new tail is returned
    d._buf += "FATAL EXCEPTION: boom\n"
    assert d.logcat_new().strip() == "FATAL EXCEPTION: boom"
