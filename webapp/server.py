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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from engine import device as device_mod  # noqa: E402
from engine.loader import load_testcase  # noqa: E402


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
    result = run(os.path.join(ROOT, test), dev, apk_path=apk or None)
    return {"overall": result["overall"], "run_id": result["run_id"],
            "counts": result["counts"], "report": f"/reports/{result['run_id']}/report.html"}


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
