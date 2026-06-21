"""
HTTP-level security regression tests for serve.py (B2 hardening).

No network, no `claude -p`. Boots the real Handler on an ephemeral loopback
port against a temporary projects root and asserts the security properties the
B2 changes are responsible for:

  - no wildcard CORS header                          (C1 / F3)
  - Content-Security-Policy + nosniff present        (F1)
  - raw .jsonl transcripts are never served          (C1)
  - no directory listings                            (C1)
  - a mutating POST without application/json is 415  (F2 CSRF guard)
  - the dashboard route rejects a malformed id       (C4)
  - a legit non-transcript static file still serves  (no regression)

Run with: python3 test_serve_security.py
"""

from __future__ import annotations

import http.server
import os
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

UUID = "17884243-1430-4c1d-9f58-ec24f487a257"
HASH = "-test-proj"

# Build a fake projects tree BEFORE importing serve (serve reads PROJECTS_ROOT
# from the env at import time): one project, one session transcript, one
# session dir holding a transcript-shaped file and a harmless static asset.
_tmp = tempfile.mkdtemp(prefix="ccd-sec-test-")
os.environ["CLAUDE_PROJECTS_DIR"] = _tmp
_proj = Path(_tmp) / HASH
_proj.mkdir(parents=True)
(_proj / f"{UUID}.jsonl").write_text('{"type":"user","text":"secret"}\n')
_sess = _proj / UUID
_sess.mkdir()
(_sess / "shot.png").write_bytes(b"\x89PNG\r\n\x1a\n fake")

import serve  # noqa: E402  (must follow env + tree setup)

_httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
_PORT = _httpd.server_address[1]
threading.Thread(target=_httpd.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{_PORT}"


def _req(method, path, headers=None, data=None):
    req = urllib.request.Request(BASE + path, method=method, headers=headers or {}, data=data)
    try:
        resp = urllib.request.urlopen(req, timeout=5)
        return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_no_wildcard_cors_and_csp_present():
    status, headers, _ = _req("GET", "/")
    assert status == 200, f"landing status was {status}"
    assert "Access-Control-Allow-Origin" not in headers, "wildcard CORS still present"
    csp = headers.get("Content-Security-Policy", "")
    assert "connect-src 'self'" in csp, f"CSP missing connect-src 'self': {csp!r}"
    assert "default-src 'none'" in csp, f"CSP missing default-src 'none': {csp!r}"
    assert headers.get("X-Content-Type-Options") == "nosniff", "nosniff missing"
    print("ok: no CORS wildcard; CSP (connect-src 'self') + nosniff present")


def test_raw_transcript_not_served():
    path = f"/{HASH}/{UUID}.jsonl"
    status, _, body = _req("GET", path)
    assert status == 404, f"raw transcript {path} was served (status {status})"
    assert b"secret" not in body, "transcript body leaked in the 404"
    print("ok: raw .jsonl transcript returns 404, no body leak")


def test_no_directory_listing():
    path = f"/{HASH}/{UUID}/"
    status, _, _ = _req("GET", path)
    assert status == 404, f"directory listing exposed at {path} (status {status})"
    print("ok: session-dir listing returns 404")


def test_regen_post_requires_json_content_type():
    status, _, _ = _req(
        "POST", "/api/regen",
        headers={"Content-Type": "text/plain"},
        data=b'{"session":"' + UUID.encode() + b'"}',
    )
    assert status == 415, f"non-json POST to /api/regen not rejected (status {status})"
    print("ok: POST /api/regen without application/json returns 415")


def test_dashboard_route_rejects_bad_session_id():
    path = f"/{HASH}/not-a-uuid/dashboard.html"
    status, _, _ = _req("GET", path)
    assert status == 400, f"malformed session id not rejected at {path} (status {status})"
    print("ok: dashboard route rejects a malformed session id (400)")


def test_legit_static_file_still_served():
    path = f"/{HASH}/{UUID}/shot.png"
    status, headers, _ = _req("GET", path)
    assert status == 200, f"legit static file not served at {path} (status {status})"
    assert headers.get("Content-Type") == "image/png", headers.get("Content-Type")
    print("ok: legit non-transcript static file still served (200, image/png)")


def test_metrics_endpoint_reports_totals():
    import pathlib
    import tempfile
    import json as _json
    import store as _store_mod
    st = _store_mod.DashboardStore(pathlib.Path(tempfile.mkdtemp()) / "dashboard.db")
    st.record(project_hash=HASH, session_uuid=UUID, status="ok",
              input_tokens=123, output_tokens=45, cost_usd=0.01, wall_ms=2000)
    serve.STORE = st
    try:
        status, _, body = _req("GET", "/api/metrics.json")
        assert status == 200, f"metrics endpoint status {status}"
        d = _json.loads(body)
        assert d["regens"] == 1, d
        assert d["input_tokens"] == 123, d
        assert d["output_tokens"] == 45, d
    finally:
        serve.STORE = None
    print("ok: /api/metrics.json reports totals")


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"\nAll {len(tests)} security regression tests passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        _httpd.shutdown()
