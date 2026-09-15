"""Engine harness — one command that says whether the engine is correct AND fast.

    py tools/harness.py

Runs a battery of correctness + complexity checks (see tools/perf.py) and prints a
report. Exits non-zero if anything fails, so it drops straight into CI or a
pre-push hook. The complexity checks assert *scaling ratios*, not wall-clock, so
they hold on any machine.
"""
from __future__ import annotations

import os
import sys

for _s in (sys.stdout, sys.stderr):     # box-drawing/✓ glyphs on a cp1252 console
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.perf import run_all  # noqa: E402

_G = "\033[92m"
_R = "\033[91m"
_D = "\033[2m"
_0 = "\033[0m"


def main() -> int:
    if os.name == "nt":
        os.system("")  # enable ANSI on Windows terminals
    print()
    print(f"  {'═' * 60}")
    print(f"   MOBILE-QA ENGINE HARNESS  ·  correctness + complexity")
    print(f"  {'═' * 60}")
    checks = run_all()
    width = max(len(c.name) for c in checks)
    for c in checks:
        mark = f"{_G}✓{_0}" if c.ok else f"{_R}✗{_0}"
        verdict = f" {_D}[{c.verdict}]{_0}" if c.verdict else ""
        print(f"   {mark}  {c.name.ljust(width)}   {c.detail}{verdict}")
    passed = sum(1 for c in checks if c.ok)
    total = len(checks)
    print(f"  {'─' * 60}")
    color = _G if passed == total else _R
    print(f"   {color}{passed}/{total} checks passed{_0}")
    print()
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
