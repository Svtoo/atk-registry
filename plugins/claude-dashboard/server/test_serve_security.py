"""HTTP-level security tests for serve.py: boots the real Handler on an
ephemeral loopback port against a temporary projects root.
Run with: python3 test_serve_security.py"""

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

# serve reads PROJECTS_ROOT from the env at import time, so the fake projects
# tree must exist first.
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


def test_raw_transcript_not_served():
    path = f"/{HASH}/{UUID}.jsonl"
    status, _, body = _req("GET", path)
    assert status == 404, f"raw transcript {path} was served (status {status})"
    assert b"secret" not in body, "transcript body leaked in the 404"


def test_no_directory_listing():
    path = f"/{HASH}/{UUID}/"
    status, _, _ = _req("GET", path)
    assert status == 404, f"directory listing exposed at {path} (status {status})"


def test_regen_post_requires_json_content_type():
    status, _, _ = _req(
        "POST", "/api/regen",
        headers={"Content-Type": "text/plain"},
        data=b'{"session":"' + UUID.encode() + b'"}',
    )
    assert status == 415, f"non-json POST to /api/regen not rejected (status {status})"


def test_dashboard_route_rejects_bad_session_id():
    path = f"/{HASH}/not-a-uuid/dashboard.html"
    status, _, _ = _req("GET", path)
    assert status == 400, f"malformed session id not rejected at {path} (status {status})"


def test_legit_static_file_still_served():
    path = f"/{HASH}/{UUID}/shot.png"
    status, headers, _ = _req("GET", path)
    assert status == 200, f"legit static file not served at {path} (status {status})"
    assert headers.get("Content-Type") == "image/png", headers.get("Content-Type")


def test_dashboard_status_excludes_the_model_and_supports_304():
    import json as _json
    serve.CHAT_STATE = serve.ChatState(projects_root=Path(_tmp))
    try:
        path = f"/api/dashboard/{HASH}/{UUID}.json"
        status, headers, body = _req("GET", path)
        assert status == 200, f"status endpoint returned {status}"
        d = _json.loads(body)
        assert "model" not in d, "the DashboardModel must never ride along on the status poll"
        etag = headers.get("ETag")
        assert etag, "the status response must carry an ETag"
        status2, headers2, body2 = _req("GET", path, headers={"If-None-Match": etag})
        assert status2 == 304, f"matching If-None-Match must return 304, got {status2}"
        assert body2 == b"", "a 304 must carry no body"
    finally:
        serve.CHAT_STATE = None


def test_metrics_endpoint_reports_totals():
    import json as _json
    import store as _store_mod
    st = _store_mod.DashboardStore(Path(tempfile.mkdtemp()) / "dashboard.db")
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


def test_dashboard_status_ok_for_fresh_chat_without_subdir():
    # A brand-new chat has a transcript but no <uuid>/ session dir yet (created
    # on first regen/error). The status endpoint must return 200 with an empty
    # default so the pending placeholder's poll succeeds — NOT 404 (which the UI
    # renders as "server unreachable"). A chat with no transcript at all is 404.
    import json as _json
    fresh = "aaaaaaaa-1111-4222-8333-444444444444"
    (_proj / f"{fresh}.jsonl").write_text('{"type":"user"}\n')  # transcript, no subdir
    serve.CHAT_STATE = serve.ChatState(projects_root=Path(_tmp))
    try:
        status, _, body = _req("GET", f"/api/dashboard/{HASH}/{fresh}.json")
        assert status == 200, f"fresh dashboard-less chat status {status}"
        d = _json.loads(body)
        assert d["hasDashboard"] is False, d
        assert d["regenErrors"] == [] and d["acks"] == {}, d
        ghost = "bbbbbbbb-2222-4333-8444-555555555555"  # no transcript at all
        status2, _, _ = _req("GET", f"/api/dashboard/{HASH}/{ghost}.json")
        assert status2 == 404, f"nonexistent chat status {status2}"
    finally:
        serve.CHAT_STATE = None


def test_verdict_endpoint_roundtrip_and_validation():
    import json as _json
    serve.CHAT_STATE = serve.ChatState(projects_root=Path(_tmp))
    try:
        item_id = "c9"
        verdict = "dismissed"
        base = f"/api/dashboard/{HASH}/{UUID}/verdict/cta/{item_id}"
        status, _, body = _req(
            "POST", base, headers={"Content-Type": "application/json"},
            data=_json.dumps({"verdict": verdict}).encode())
        assert status == 200, f"verdict POST returned {status}: {body!r}"
        status, _, body = _req("GET", f"/api/dashboard/{HASH}/{UUID}.json")
        d = _json.loads(body)
        assert d["verdicts"][f"cta:{item_id}"]["verdict"] == verdict, d
        status, _, _ = _req("DELETE", base, headers={"Content-Type": "application/json"})
        assert status == 200, f"verdict undo returned {status}"
        _, _, body = _req("GET", f"/api/dashboard/{HASH}/{UUID}.json")
        assert _json.loads(body)["verdicts"] == {}, "undo must clear the verdict"

        bad = [
            (f"/api/dashboard/{HASH}/{UUID}/verdict/cta/c9", b'{"verdict": "done"}'),
            (f"/api/dashboard/{HASH}/{UUID}/verdict/freeform/f1", b'{"verdict": "dropped"}'),
            (f"/api/dashboard/{HASH}/{UUID}/verdict/todo/t1", b'{"verdict": "obliterated"}'),
        ]
        for path, payload in bad:
            status, _, _ = _req("POST", path,
                                headers={"Content-Type": "application/json"}, data=payload)
            assert status == 400, f"{path} with {payload!r} must 400, got {status}"
    finally:
        serve.CHAT_STATE = None


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
