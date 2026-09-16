"""Device layer — the ONLY place that touches ADB / uiautomator2.

Two things live here:

  * :class:`Device` / :class:`Element` — the small abstract interface every
    engine module is allowed to use. Because it is small and abstract, the test
    suite can drop in a ``FakeDevice`` and drive the entire engine with no
    Android present. The real :class:`AndroidDevice` is a thin wrapper over
    uiautomator2 + adb.

  * :func:`probe_environment` — capability diagnosis for ``cli.py --check-env``.
    It never throws; it reports what is present and whether a live run is
    possible.

Design rule: nothing above this file imports ``uiautomator2`` or shells out to
``adb``/``aapt``. If it needs the device, it goes through this interface.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from abc import ABC, abstractmethod
from typing import Any, Optional

from . import config
from . import models

# Selector kinds understood by Device.find (see resolver.py for priority order)
SELECTOR_KINDS = (
    models.STRATEGY_RESOURCE_ID,
    models.STRATEGY_TEXT_EXACT,
    models.STRATEGY_TEXT_CONTAINS,
    models.STRATEGY_DESC,
)


class DeviceError(RuntimeError):
    """Raised for unrecoverable device/tooling problems (with a clear message)."""


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------
class Element(ABC):
    """A located on-screen element. The engine only uses these four things."""

    @abstractmethod
    def click(self) -> None: ...

    def long_click(self) -> None:
        """Long-press this element. Default falls back to a tap; the live
        adapter overrides it with a real long press."""
        self.click()

    @abstractmethod
    def set_text(self, value: str) -> None: ...

    @abstractmethod
    def center(self) -> tuple[int, int]: ...

    @abstractmethod
    def exists(self) -> bool: ...


class Device(ABC):
    """The device surface the engine is allowed to use.

    Keep this list small — every method here is something ``FakeDevice`` must
    also implement, and every method here is a promise the engine relies on.
    """

    # --- lifecycle -----------------------------------------------------------
    @abstractmethod
    def install(self, apk_path: str) -> None: ...

    @abstractmethod
    def launch(self, package: str, activity: Optional[str] = None) -> None: ...

    @abstractmethod
    def stop(self, package: str) -> None: ...

    @abstractmethod
    def clear_data(self, package: str) -> None: ...

    # --- perception ----------------------------------------------------------
    @abstractmethod
    def screenshot(self, path: str) -> str: ...

    @abstractmethod
    def dump_hierarchy(self) -> str: ...

    def invalidate(self) -> None:
        """Drop any memoized screen read. Default no-op; the live adapter
        overrides it. Called after every action so the next read is fresh."""

    @abstractmethod
    def current_activity(self) -> Optional[str]: ...

    @abstractmethod
    def current_package(self) -> Optional[str]: ...

    @abstractmethod
    def keyboard_visible(self) -> bool: ...

    @abstractmethod
    def logcat_since_launch(self) -> str: ...

    # --- interaction ---------------------------------------------------------
    @abstractmethod
    def find(self, kind: str, value: str) -> Optional[Element]: ...

    @abstractmethod
    def tap_xy(self, x: int, y: int) -> None: ...

    def long_click_xy(self, x: int, y: int) -> None:
        """Long-press at coordinates. Default falls back to a tap; the live
        adapter overrides it with a real long press."""
        self.tap_xy(x, y)

    @abstractmethod
    def input_text(self, value: str) -> None:
        """Type into the currently focused field (used after an OCR tap)."""

    @abstractmethod
    def scroll_forward(self) -> None: ...

    @abstractmethod
    def press_back(self) -> None: ...

    @abstractmethod
    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.2) -> None: ...


# ---------------------------------------------------------------------------
# Real Android implementation (uiautomator2 + adb)
# ---------------------------------------------------------------------------
class _U2Element(Element):
    def __init__(self, sel: Any, owner: Optional["AndroidDevice"] = None):
        self._sel = sel
        self._owner = owner

    def _touched(self) -> None:
        if self._owner is not None:
            self._owner.invalidate()

    def click(self) -> None:
        self._sel.click()
        self._touched()

    def long_click(self) -> None:
        try:
            self._sel.long_click()
        except Exception:
            self._sel.click()   # element handle without long_click support
        self._touched()

    def set_text(self, value: str) -> None:
        self._sel.set_text(value)
        self._touched()

    def center(self) -> tuple[int, int]:
        # Prefer u2's own center(); fall back to computing from bounds if the
        # installed version or a given element doesn't provide it.
        try:
            x, y = self._sel.center()
            return (int(x), int(y))
        except Exception:
            b = self._sel.info["bounds"]
            return ((b["left"] + b["right"]) // 2, (b["top"] + b["bottom"]) // 2)

    def exists(self) -> bool:
        return bool(self._sel.exists)


class AndroidDevice(Device):
    """Thin wrapper over a live device via uiautomator2 + adb.

    Constructed by :func:`connect`. A fatal-logcat marker is planted at launch
    so :func:`logcat_since_launch` only returns lines produced during the run.
    """

    def __init__(self, u2_device: Any, serial: Optional[str] = None):
        self._d = u2_device
        self.serial = serial
        self._hier_cache: Optional[str] = None
        self._act_cache: Optional[str] = None
        self._cache_valid = False

    def invalidate(self) -> None:
        """Drop the memoized hierarchy/activity so the next read is live. Called
        by every mutating action below."""
        self._cache_valid = False
        self._hier_cache = None
        self._act_cache = None

    # -- adb plumbing ---------------------------------------------------------
    def _adb(self, *args: str, timeout: int = 60) -> str:
        cmd = ["adb"]
        if self.serial:
            cmd += ["-s", self.serial]
        cmd += list(args)
        # Force UTF-8 + replace: logcat/dumpsys emit bytes the Windows locale
        # (cp1252) cannot decode, which otherwise crashes the reader threads.
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                             encoding="utf-8", errors="replace")
        if out.returncode != 0:
            raise DeviceError(f"adb {' '.join(args)} failed: {out.stderr.strip()}")
        return out.stdout

    # -- lifecycle ------------------------------------------------------------
    def install(self, apk_path: str) -> None:
        self._adb("install", "-r", "-g", apk_path, timeout=300)

    def launch(self, package: str, activity: Optional[str] = None) -> None:
        # Plant a clean logcat baseline so crash detection is scoped to this run.
        try:
            self._adb("logcat", "-c")
        except DeviceError:
            pass
        self._d.app_start(package, activity, stop=True)
        self.invalidate()

    def stop(self, package: str) -> None:
        self._d.app_stop(package)

    def clear_data(self, package: str) -> None:
        self._adb("shell", "pm", "clear", package)
        self.invalidate()

    # -- perception -----------------------------------------------------------
    def screenshot(self, path: str) -> str:
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        self._d.screenshot(path)
        return path

    def dump_hierarchy(self) -> str:
        """Memoized within one screen state — see config.HIERARCHY_CACHE. The
        memo holds until the next mutating action calls ``invalidate()``."""
        if config.HIERARCHY_CACHE and self._cache_valid and self._hier_cache is not None:
            return self._hier_cache
        xml = self._d.dump_hierarchy()
        if config.HIERARCHY_CACHE:
            self._hier_cache = xml
            self._cache_valid = True
        return xml

    def current_activity(self) -> Optional[str]:
        if config.HIERARCHY_CACHE and self._cache_valid and self._act_cache is not None:
            return self._act_cache
        try:
            act = self._d.app_current().get("activity")
        except Exception:
            act = None
        if config.HIERARCHY_CACHE and act is not None:
            self._act_cache = act
        return act

    def current_package(self) -> Optional[str]:
        try:
            return self._d.app_current().get("package")
        except Exception:
            return None

    def keyboard_visible(self) -> bool:
        try:
            out = self._adb("shell", "dumpsys", "input_method")
        except DeviceError:
            return False
        return "mInputShown=true" in out

    def logcat_since_launch(self) -> str:
        try:
            return self._adb("logcat", "-d")
        except DeviceError:
            return ""

    # -- interaction ----------------------------------------------------------
    def find(self, kind: str, value: str) -> Optional[Element]:
        d = self._d
        if kind == models.STRATEGY_RESOURCE_ID:
            sel = d(resourceId=value)
        elif kind == models.STRATEGY_TEXT_EXACT:
            sel = d(text=value)
        elif kind == models.STRATEGY_TEXT_CONTAINS:
            sel = d(textContains=value)
        elif kind == models.STRATEGY_DESC:
            sel = d(description=value)
        else:
            raise DeviceError(f"unknown selector kind: {kind}")
        return _U2Element(sel, owner=self) if sel.exists else None

    def tap_xy(self, x: int, y: int) -> None:
        self._d.click(x, y)
        self.invalidate()

    def long_click_xy(self, x: int, y: int) -> None:
        try:
            self._d.long_click(x, y, config.LONG_PRESS_S)
        except Exception:
            self._d.click(x, y)
        self.invalidate()

    def input_text(self, value: str) -> None:
        self._d.send_keys(value)
        self.invalidate()

    def scroll_forward(self) -> None:
        try:
            self._d(scrollable=True).scroll.forward()
        except Exception:
            w, h = self._d.window_size()
            self._d.swipe(w // 2, int(h * 0.7), w // 2, int(h * 0.3), 0.3)
        self.invalidate()

    def press_back(self) -> None:
        self._d.press("back")
        self.invalidate()

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.2) -> None:
        self._d.swipe(x1, y1, x2, y2, duration)
        self.invalidate()


# ---------------------------------------------------------------------------
# Connection + APK metadata
# ---------------------------------------------------------------------------
def connect(serial: Optional[str] = None) -> AndroidDevice:
    """Connect to a live device via uiautomator2, or raise a clear DeviceError.

    Kept import-lazy so the engine and its tests import fine without a device
    or even without uiautomator2 installed.
    """
    if shutil.which("adb") is None:
        raise DeviceError("adb not found on PATH — install Android platform-tools "
                          "(see docs/SETUP_ANDROID.md).")
    try:
        import uiautomator2 as u2
    except ImportError as exc:  # pragma: no cover - env dependent
        raise DeviceError("uiautomator2 not installed — run "
                          "`pip install -r requirements.txt`.") from exc

    devices = _adb_devices()
    if not devices:
        raise DeviceError("No Android device/emulator detected (`adb devices` is "
                          "empty). Connect a device or start an AVD — see "
                          "docs/SETUP_ANDROID.md.")
    serial = serial or devices[0]
    try:
        d = u2.connect(serial)
    except Exception as exc:  # pragma: no cover - env dependent
        raise DeviceError(f"uiautomator2 could not connect to {serial}: {exc}") from exc
    return AndroidDevice(d, serial=serial)


def _adb_devices() -> list[str]:
    if shutil.which("adb") is None:
        return []
    try:
        out = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=15,
                             encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return []
    serials: list[str] = []
    for line in out.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) == 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials


def read_apk_metadata(apk_path: str) -> dict[str, Optional[str]]:
    """Return {'package', 'launch_activity'} for an APK using aapt/aapt2.

    Raises DeviceError with an actionable message if neither tool is available.
    """
    tool = shutil.which("aapt") or shutil.which("aapt2")
    if tool is None:
        raise DeviceError("Neither aapt nor aapt2 found on PATH — install Android "
                          "build-tools (see docs/SETUP_ANDROID.md).")
    out = subprocess.run([tool, "dump", "badging", apk_path],
                         capture_output=True, text=True, timeout=60,
                         encoding="utf-8", errors="replace")
    if out.returncode != 0:
        raise DeviceError(f"{tool} could not read {apk_path}: {out.stderr.strip()}")
    text = out.stdout
    pkg = _search(r"package: name='([^']+)'", text)
    activity = _search(r"launchable-activity: name='([^']+)'", text)
    return {"package": pkg, "launch_activity": activity}


def _search(pattern: str, text: str) -> Optional[str]:
    m = re.search(pattern, text)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Environment probe (cli --check-env)
# ---------------------------------------------------------------------------
# label -> (kind, importable module or None, binary name or None)
def probe_environment() -> dict[str, Any]:
    """Diagnose capabilities without throwing. Returns a structured report the
    CLI renders as a table plus a readiness rollup."""
    import sys

    def bin_present(name: str) -> Optional[str]:
        return shutil.which(name)

    def module_present(name: str) -> bool:
        try:
            __import__(name)
            return True
        except Exception:
            return False

    checks: list[dict[str, Any]] = []

    checks.append({
        "name": "python", "status": "FOUND", "level": "REQUIRED",
        "detail": sys.version.split()[0],
    })

    for label, binname, level in [
        ("adb", "adb", "REQUIRED-FOR-LIVE-RUN"),
        ("aapt", "aapt", "REQUIRED-FOR-LIVE-RUN"),   # aapt OR aapt2 satisfies this
        ("tesseract", "tesseract", "REQUIRED"),
        ("emulator", "emulator", "OPTIONAL"),
    ]:
        path = bin_present(binname)
        if label == "aapt" and path is None:
            path = bin_present("aapt2")
        checks.append({
            "name": label,
            "status": "FOUND" if path else "MISSING",
            "level": level,
            "detail": path or "",
        })

    for label, mod, level in [
        ("uiautomator2", "uiautomator2", "REQUIRED-FOR-LIVE-RUN"),
        ("pytesseract", "pytesseract", "REQUIRED"),
        ("Pillow", "PIL", "REQUIRED"),
        ("pyyaml", "yaml", "REQUIRED"),
    ]:
        ok = module_present(mod)
        checks.append({
            "name": label,
            "status": "FOUND" if ok else "MISSING",
            "level": level,
            "detail": "",
        })

    devices = _adb_devices()
    checks.append({
        "name": "device",
        "status": "FOUND" if devices else "MISSING",
        "level": "REQUIRED-FOR-LIVE-RUN",
        "detail": ", ".join(devices) if devices else "no Android target detected",
    })

    def ok(name: str) -> bool:
        return any(c["name"] == name and c["status"] == "FOUND" for c in checks)

    core_ready = all(ok(n) for n in ("python", "tesseract", "pytesseract", "Pillow", "pyyaml"))
    live_ready = core_ready and all(ok(n) for n in ("adb", "aapt", "uiautomator2", "device"))

    return {
        "checks": checks,
        "core_ready": core_ready,
        "live_ready": live_ready,
        "devices": devices,
    }
