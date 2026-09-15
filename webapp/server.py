"""webapp/server.py — a tiny local control panel over the existing engine.

Pure Python stdlib (no new deps). Every endpoint is a thin call into functions
that already exist (``device_mod.probe_environment``, ``engine.runner.run``,
``cli.cmd_inspect``'s capture, the screen library) — no engine logic is
duplicated here. Read-only panels (env, test cases, screens, reports) work with
no device; capture/run need a connected device.

Run with ``py cli.py web`` (see cli.cmd_web) or ``py -m webapp.server``.
"""
from __future__ import annotations

import json
import os
import sys
import glob
import shutil
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from engine import device as device_mod  # noqa: E402
from engine.loader import load_testcase  # noqa: E402

# Booted with a window so a human can drive between captures; headless-friendly
# flags otherwise. Overridable per-request via the emulator endpoint's payload.
_EMULATOR_FLAGS = ["-no-audio", "-no-snapshot", "-gpu", "swiftshader_indirect"]


def _testcases() -> list[dict[str, Any]]:
    out = []
    for path in sorted(glob.glob(os.path.join(ROOT, "testcases", "*.yaml"))):
        rel = os.path.relpath(path, ROOT)
        try:
            tc = load_testcase(path)
            out.append({"path": rel, "name": tc["name"], "package": tc["package"],
                        "steps": len(tc.get("steps", []))})
        except Exception as exc:
            out.append({"path": rel, "name": os.path.basename(path),
                        "package": None, "steps": None, "error": str(exc)})
    return out


def _reports() -> list[dict[str, Any]]:
    out = []
    for d in sorted(glob.glob(os.path.join(ROOT, "reports", "*")), reverse=True):
        tl = os.path.join(d, "timeline.json")
        run_id = os.path.basename(d)
        meta = {}
        try:
            with open(tl, encoding="utf-8") as fh:
                meta = json.load(fh).get("meta", {})
        except Exception:
            continue
        out.append({"run_id": run_id, "overall": meta.get("overall"),
                    "name": meta.get("name"), "counts": meta.get("counts", {}),
                    "report": f"/reports/{run_id}/report.html"})
        if len(out) >= 50:
            break
    return out


def _screens(package: str) -> dict[str, Any]:
    from engine.screen_library import ScreenLibrary
    lib = ScreenLibrary(package)
    rows = []
    for s in lib.screens():
        els = s.get("elements", [])
        rows.append({"label": s["label"], "activity": s.get("activity"),
                     "fingerprint": s.get("structural_fingerprint"),
                     "elements": len(els),
                     "tappable": sum(1 for e in els if e.get("clickable")),
                     "fields": sum(1 for e in els if e.get("editable")),
                     "screenshot": s.get("screenshot")})
    return {"package": package, "screens": rows}


def _capture(label: str, serial: str | None) -> dict[str, Any]:
    """Drive-capture the current screen into the library (needs a device)."""
    from engine.observation import observe
    from engine.screen_library import ScreenLibrary
    dev = device_mod.connect(serial=serial or None)
    out_dir = os.path.join(ROOT, "screens", "_web", label)
    os.makedirs(out_dir, exist_ok=True)
    obs = observe(dev, os.path.join(out_dir, "screenshot.png"))
    lib = ScreenLibrary(obs.package or "app")
    lib.add(obs, label, screenshot=os.path.join(out_dir, "screenshot.png"))
    lib.save()
    return {"label": label, "package": obs.package, "activity": obs.activity,
            "fingerprint": obs.structural_fingerprint(),
            "elements": len(obs.elements()), "screens": len(lib.screens())}


def _run(test: str, apk: str | None, serial: str | None) -> dict[str, Any]:
    from engine.runner import run
    dev = device_mod.connect(serial=serial or None)
    apk_path = os.path.join(ROOT, apk) if apk else None
    result = run(os.path.join(ROOT, test), dev, apk_path=apk_path)
    return {"overall": result["overall"], "run_id": result["run_id"],
            "counts": result["counts"], "report": f"/reports/{result['run_id']}/report.html",
            "diagnostics": _diagnostics(result.get("results") or [])}


def _diagnostics(results: list) -> list[dict[str, Any]]:
    """Per non-PASS step: the reason, the screen, and the nearest ranked matches
    — the same data ``cli._print_diagnostics`` prints, shaped as JSON."""
    out = []
    for i, r in enumerate(results):
        status = getattr(getattr(r, "status", None), "value", None)
        if not status or status == "PASS":
            continue
        sugg = []
        for c in (getattr(r, "suggestions", None) or []):
            lbl = (c.get("text") or c.get("content_desc")
                   or c.get("resource_id") or "").strip() or "(no label)"
            sugg.append({"score": round(c.get("score", 0), 2),
                         "kind": c.get("kind", ""), "label": lbl})
        out.append({
            "index": i, "status": status,
            "action": getattr(r, "action", None) or "assert",
            "target": getattr(r, "target", None),
            "reason": getattr(r, "failure_reason", None),
            "detail": getattr(r, "detail", "") or getattr(r, "error", ""),
            "screen": getattr(r, "screen_summary", None),
            "suggestions": sugg,
        })
    return out


def _avds() -> list[str]:
    exe = shutil.which("emulator")
    if not exe:
        return []
    try:
        out = subprocess.run([exe, "-list-avds"], capture_output=True, text=True,
                             timeout=15)
        return [line.strip() for line in out.stdout.splitlines() if line.strip()]
    except (OSError, subprocess.SubprocessError):
        return []


def _apks() -> list[dict[str, str]]:
    rows = []
    for path in sorted(glob.glob(os.path.join(ROOT, "apks", "*.apk"))):
        rows.append({"path": os.path.relpath(path, ROOT).replace("\\", "/"),
                     "name": os.path.basename(path)})
    return rows


def _emulator(action: str, avd: str | None, serial: str | None) -> dict[str, Any]:
    """Start an AVD (detached; poll /api/env for readiness) or kill a running one."""
    if action == "start":
        exe = shutil.which("emulator")
        if not exe:
            raise device_mod.DeviceError("emulator not found on PATH")
        if not avd:
            avds = _avds()
            if not avds:
                raise device_mod.DeviceError("no AVDs found — create one in Android Studio")
            avd = avds[0]
        flags = ["-avd", avd, *_EMULATOR_FLAGS]
        creation = getattr(subprocess, "DETACHED_PROCESS", 0) | \
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen([exe, *flags], cwd=ROOT, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         creationflags=creation if os.name == "nt" else 0,
                         start_new_session=(os.name != "nt"))
        return {"starting": True, "avd": avd,
                "note": "booting — watch the Environment panel for the device"}
    if action == "stop":
        adb = shutil.which("adb") or "adb"
        cmd = [adb] + (["-s", serial] if serial else []) + ["emu", "kill"]
        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError) as exc:
            raise device_mod.DeviceError(f"could not stop emulator: {exc}")
        return {"stopped": True}
    raise device_mod.DeviceError(f"unknown emulator action {action!r}")


def _launch(package: str, serial: str | None) -> dict[str, Any]:
    """Open an installed app to its launcher screen so it can be driven/captured."""
    adb = shutil.which("adb") or "adb"
    cmd = [adb] + (["-s", serial] if serial else []) + \
        ["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if out.returncode != 0 or "No activities found" in (out.stdout + out.stderr):
        raise device_mod.DeviceError(
            f"could not launch {package} (installed? correct package?)")
    return {"launched": True, "package": package}


def _preflight(test: str) -> dict[str, Any]:
    """Match a test's targets to the captured screen library (no device)."""
    from engine.screen_library import ScreenLibrary
    tc = load_testcase(os.path.join(ROOT, test))
    package = tc["package"]
    lib = ScreenLibrary(package)
    if not lib.screens():
        return {"package": package, "captured": 0, "rows": [], "unknown": 0,
                "message": f"No screens captured for {package} yet."}
    rows, unknown = [], 0
    for i, step in enumerate(tc.get("steps", [])):
        if "action" not in step:
            continue
        target = step.get("target")
        if not target:
            continue
        query = target if isinstance(target, str) else (
            target.get("label") or target.get("text") or target.get("desc")
            or (target.get("id", "").rsplit("/", 1)[-1] if target.get("id") else ""))
        if not query:
            continue
        role = "field" if step["action"] in ("type", "enter_text") else "tappable"
        bearing = lib.find_bearing(query, role)
        if bearing:
            rows.append({"index": i, "action": step["action"], "query": query,
                         "found": True, "screen": bearing["label"],
                         "center": bearing["center"]})
        else:
            unknown += 1
            rows.append({"index": i, "action": step["action"], "query": query,
                         "found": False})
    return {"package": package, "captured": len(lib.screens()), "rows": rows,
            "unknown": unknown}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj: Any, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

    def log_message(self, *a):  # quiet
        pass

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        query = {}
        if "?" in self.path:
            from urllib.parse import parse_qs
            query = {k: v[0] for k, v in parse_qs(self.path.split("?", 1)[1]).items()}
        try:
            if path == "/" or path == "/index.html":
                with open(os.path.join(os.path.dirname(__file__), "index.html"), "rb") as fh:
                    return self._send(200, fh.read(), "text/html; charset=utf-8")
            if path == "/api/env":
                return self._json(device_mod.probe_environment())
            if path == "/api/testcases":
                return self._json(_testcases())
            if path == "/api/reports":
                return self._json(_reports())
            if path == "/api/screens":
                return self._json(_screens(query.get("package", "")))
            if path == "/api/avds":
                return self._json({"avds": _avds()})
            if path == "/api/apks":
                return self._json({"apks": _apks()})
            if path == "/api/preflight":
                test = query.get("test")
                if not test:
                    return self._json({"error": "missing test"}, 400)
                return self._json(_preflight(test))
            if path.startswith("/reports/"):
                return self._serve_static(path)
            return self._json({"error": "not found"}, 404)
        except Exception as exc:
            return self._json({"error": str(exc)}, 500)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._json({"error": "bad json"}, 400)
        try:
            if self.path == "/api/inspect":
                return self._json(_capture(payload.get("label", "screen"),
                                           payload.get("serial")))
            if self.path == "/api/run":
                return self._json(_run(payload["test"], payload.get("apk"),
                                       payload.get("serial")))
            if self.path == "/api/emulator":
                return self._json(_emulator(payload.get("action", ""),
                                            payload.get("avd"), payload.get("serial")))
            if self.path == "/api/launch":
                return self._json(_launch(payload["package"], payload.get("serial")))
            return self._json({"error": "not found"}, 404)
        except KeyError as exc:
            return self._json({"error": f"missing field {exc}"}, 400)
        except device_mod.DeviceError as exc:
            return self._json({"error": f"device: {exc}"}, 503)
        except Exception as exc:
            return self._json({"error": str(exc)}, 500)

    def _serve_static(self, path: str) -> None:
        # Serve report files, safely scoped under reports/.
        rel = path.lstrip("/")
        full = os.path.normpath(os.path.join(ROOT, rel))
        reports_root = os.path.join(ROOT, "reports")
        if not full.startswith(reports_root) or not os.path.isfile(full):
            return self._json({"error": "not found"}, 404)
        ctype = ("text/html; charset=utf-8" if full.endswith(".html")
                 else "image/png" if full.endswith(".png")
                 else "application/json" if full.endswith(".json")
                 else "application/octet-stream")
        with open(full, "rb") as fh:
            return self._send(200, fh.read(), ctype)


def serve(port: int = 8765) -> None:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Mobile QA web panel → http://localhost:{port}   (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else 8765)
