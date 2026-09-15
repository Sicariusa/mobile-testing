"""Web control-panel endpoints — the read-only ones work with no device, and
the report path is escape-guarded. Runs a real server on an ephemeral port."""
from __future__ import annotations

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from webapp import server as web


def _get(base, path):
    with urllib.request.urlopen(base + path) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def _server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def test_readonly_endpoints_work_without_a_device():
    httpd, base = _server()
    try:
        code, env = _get(base, "/api/env")
        assert code == 200 and "checks" in env and "live_ready" in env

        code, tcs = _get(base, "/api/testcases")
        assert code == 200 and isinstance(tcs, list) and tcs
        assert all("path" in t for t in tcs)

        code, reps = _get(base, "/api/reports")
        assert code == 200 and isinstance(reps, list)

        code, scr = _get(base, "/api/screens?package=does.not.exist")
        assert code == 200 and scr["screens"] == []

        code, avds = _get(base, "/api/avds")
        assert code == 200 and isinstance(avds["avds"], list)

        code, apks = _get(base, "/api/apks")
        assert code == 200 and isinstance(apks["apks"], list)
    finally:
        httpd.shutdown()


def test_preflight_endpoint_reports_capture_state():
    httpd, base = _server()
    try:
        tcs = _get(base, "/api/testcases")[1]
        code, pf = _get(base, "/api/preflight?test=" + tcs[0]["path"])
        assert code == 200 and "captured" in pf and "rows" in pf
    finally:
        httpd.shutdown()


def test_preflight_without_test_is_400():
    httpd, base = _server()
    try:
        try:
            urllib.request.urlopen(base + "/api/preflight")
            ok = False
        except urllib.error.HTTPError as exc:
            ok = exc.code == 400
        assert ok
    finally:
        httpd.shutdown()


def test_report_path_traversal_is_blocked():
    httpd, base = _server()
    try:
        try:
            urllib.request.urlopen(base + "/reports/../cli.py")
            raised = False
        except urllib.error.HTTPError as exc:
            raised = exc.code == 404
        assert raised, "path traversal outside reports/ must 404"
    finally:
        httpd.shutdown()


def _post(base, path, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(base + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def test_screen_remove_and_rename_endpoints_are_wired():
    httpd, base = _server()
    try:
        # a package/id that doesn't exist: endpoints respond cleanly, no write
        code, rem = _post(base, "/api/screens/remove",
                          {"package": "does.not.exist", "id": "scr_nope"})
        assert code == 200 and rem["removed"] is False
        code, ren = _post(base, "/api/screens/rename",
                          {"package": "does.not.exist", "id": "scr_nope", "label": "x"})
        assert code == 200 and ren["renamed"] is False
    finally:
        httpd.shutdown()


def test_screens_static_path_traversal_is_blocked():
    httpd, base = _server()
    try:
        try:
            urllib.request.urlopen(base + "/screens/../cli.py")
            raised = False
        except urllib.error.HTTPError as exc:
            raised = exc.code == 404
        assert raised, "path traversal outside screens/ must 404"
    finally:
        httpd.shutdown()


def test_unknown_route_is_404():
    httpd, base = _server()
    try:
        try:
            urllib.request.urlopen(base + "/api/nope")
            ok = False
        except urllib.error.HTTPError as exc:
            ok = exc.code == 404
        assert ok
    finally:
        httpd.shutdown()
