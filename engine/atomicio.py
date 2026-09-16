"""Atomic JSON persistence — write to a temp file in the same directory and
os.replace() it over the target, so a crash or a concurrent reader never sees a
half-written file. Errors propagate: a failed write must never be mistaken for a
successful one by the caller.
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import Any


def write_json_atomic(path: str, data: Any) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)          # atomic on POSIX and Windows (same fs)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def safe_dirname(name: str, fallback: str = "app") -> str:
    """A single filesystem path segment derived from ``name`` that can never
    escape its parent directory (rejects '.'/'..' and empty)."""
    import re
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name or fallback)
    if safe in (".", "..") or not safe:
        return fallback
    return safe
