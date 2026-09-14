"""FakeDevice — a scripted, deterministic stand-in for a real Android device.

This is the keystone of the test strategy: because the whole engine reaches the
device only through the :class:`engine.device.Device` interface, a FakeDevice
lets us drive resolver / recovery / executor / validator / runner end to end
with NO Android present. Screenshots are rendered from real text with Pillow so
Tesseract OCR runs for real against them.

A test builds a list of :class:`FakeScreen` states and wires transitions
(``goto`` on an element click, ``scroll_goto`` when scrolled, ``tap_goto`` for an
OCR coordinate tap, ``input_goto`` after typing). ``FakeDevice`` walks that state
machine as the engine acts on it.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional

from PIL import Image, ImageDraw, ImageFont

from engine.device import Device, Element
from engine import models

_FONT_PATH = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"


def _font(size: int = 40):
    try:
        return ImageFont.truetype(_FONT_PATH, size)
    except Exception:  # pragma: no cover - font-availability dependent
        return ImageFont.load_default()


def render_text(path: str, lines, bg=(255, 255, 255)) -> str:
    """Render lines of text into a PNG so real Tesseract can read it back.
    Shared by FakeDevice screenshots and validator/OCR unit tests."""
    import os as _os
    _os.makedirs(_os.path.dirname(_os.path.abspath(path)), exist_ok=True)
    img = Image.new("RGB", (600, 900), bg)
    draw = ImageDraw.Draw(img)
    font = _font(44)
    y = 60
    for line in lines:
        draw.text((40, y), line, fill=(10, 10, 10), font=font)
        y += 90
    img.save(path)
    return path


@dataclass
class FakeScreen:
    name: str
    activity: str = "com.example.shop/.MainActivity"
    package: str = "com.example.shop"
    hierarchy_xml: str = "<hierarchy></hierarchy>"
    ocr_lines: tuple[str, ...] = ()          # rendered into the screenshot
    keyboard_visible: bool = False
    elements: tuple[dict[str, Any], ...] = ()  # each: id?/text?/desc?/center/goto?
    tap_goto: Optional[int] = None           # OCR coordinate tap -> this screen
    scroll_goto: Optional[int] = None        # scroll_forward -> this screen
    input_goto: Optional[int] = None         # after input_text -> this screen
    bg: tuple[int, int, int] = (255, 255, 255)


class FakeElement(Element):
    def __init__(self, dev: "FakeDevice", el: dict[str, Any]):
        self._dev = dev
        self._el = el

    def click(self) -> None:
        self._dev._goto(self._el.get("goto"))

    def set_text(self, value: str) -> None:
        self._dev.typed.append(value)
        self._dev._goto(self._el.get("goto"))

    def center(self) -> tuple[int, int]:
        return tuple(self._el.get("center", (0, 0)))

    def exists(self) -> bool:
        return True


class FakeDevice(Device):
    def __init__(self, screens: list[FakeScreen], *, logcat: str = ""):
        self.screens = screens
        self.idx = 0
        self.logcat = logcat
        self.typed: list[str] = []
        self.installed: Optional[str] = None
        self.launched = False
        self.scroll_count = 0

    # -- state machine --------------------------------------------------------
    @property
    def cur(self) -> FakeScreen:
        return self.screens[self.idx]

    def _goto(self, i: Optional[int]) -> None:
        if i is not None:
            self.idx = i

    # -- lifecycle ------------------------------------------------------------
    def install(self, apk_path: str) -> None:
        self.installed = apk_path

    def launch(self, package: str, activity: Optional[str] = None) -> None:
        self.launched = True
        self.idx = 0

    def stop(self, package: str) -> None:
        pass

    def clear_data(self, package: str) -> None:
        pass

    # -- perception -----------------------------------------------------------
    def screenshot(self, path: str) -> str:
        return render_text(path, self.cur.ocr_lines, bg=self.cur.bg)

    def dump_hierarchy(self) -> str:
        return self.cur.hierarchy_xml

    def current_activity(self) -> Optional[str]:
        return self.cur.activity

    def current_package(self) -> Optional[str]:
        return self.cur.package

    def keyboard_visible(self) -> bool:
        return self.cur.keyboard_visible

    def logcat_since_launch(self) -> str:
        return self.logcat

    # -- interaction ----------------------------------------------------------
    def find(self, kind: str, value: str) -> Optional[Element]:
        for el in self.cur.elements:
            if _matches(kind, value, el):
                return FakeElement(self, el)
        return None

    def tap_xy(self, x: int, y: int) -> None:
        self._goto(self.cur.tap_goto)

    def input_text(self, value: str) -> None:
        self.typed.append(value)
        self._goto(self.cur.input_goto)

    def scroll_forward(self) -> None:
        self.scroll_count += 1
        self._goto(self.cur.scroll_goto)

    def press_back(self) -> None:
        # dismissing the keyboard reveals the underlying screen
        self.screens[self.idx].keyboard_visible = False

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.2) -> None:
        pass


def _matches(kind: str, value: str, el: dict[str, Any]) -> bool:
    if kind == models.STRATEGY_RESOURCE_ID:
        return el.get("id") == value
    if kind == models.STRATEGY_TEXT_EXACT:
        return el.get("text") == value
    if kind == models.STRATEGY_TEXT_CONTAINS:
        return bool(el.get("text")) and value in el["text"]
    if kind == models.STRATEGY_DESC:
        return el.get("desc") == value
    return False


# --- hierarchy fixture helper ------------------------------------------------
def node(**attrs: Any) -> str:
    """Build a single uiautomator-style <node .../> element from attrs."""
    parts = " ".join(f'{k.replace("_", "-")}="{v}"' for k, v in attrs.items())
    return f"<node {parts}/>"


def hierarchy(*nodes: str) -> str:
    inner = "".join(nodes)
    return f'<?xml version="1.0" encoding="UTF-8"?><hierarchy rotation="0">{inner}</hierarchy>'
