"""Tests for the per-chat "Dashboard updates" feed (serve._chat_notices_html).
Run: python3 test_serve_feed.py
"""
from __future__ import annotations

import os
import tempfile

# serve reads PROJECTS_ROOT from the env at import time.
os.environ["CLAUDE_PROJECTS_DIR"] = tempfile.mkdtemp(prefix="ccd-feed-test-")

import serve  # noqa: E402  (must follow env setup)
from testutil import run_module_tests  # noqa: E402

HASH = "-test-proj"
UUID = "17884243-1430-4c1d-9f58-ec24f487a257"

SIGNED_OUT_KIND = "SubprocessFailed"
SIGNED_OUT_MESSAGE = "claude -p exited 1 — please run /login"
TIMEOUT_KIND = "RegenTimeout"
TIMEOUT_MESSAGE = "claude -p exceeded 180s and was killed"


def _entry(kind: str, message: str, *, at: int, acked_at=None, resolved_at=None) -> dict:
    return {
        "id": f"err-{at}-0000000a",
        "at": at,
        "kind": kind,
        "message": message,
        "ackedAt": acked_at,
        "resolvedAt": resolved_at,
    }


def _feed(entries) -> str:
    return serve._chat_notices_html(HASH, UUID, entries, typical_s=None)


def test_app_scope_entries_never_render_live():
    live_signed_out = _entry(SIGNED_OUT_KIND, SIGNED_OUT_MESSAGE, at=1755700000)
    html = _feed([live_signed_out])
    assert html == "", f"an app-scope entry rendered live in the chat feed: {html}"


def test_chat_scope_entries_render_live_with_dismiss():
    live_timeout = _entry(TIMEOUT_KIND, TIMEOUT_MESSAGE, at=1755700000)
    html = _feed([live_timeout])
    assert 'data-code="rebuild.timeout"' in html, html
    assert "dismiss" in html, f"a chat-scope card lost its dismiss control: {html}"


def test_app_scope_entries_still_fold_once_resolved():
    resolved_signed_out = _entry(
        SIGNED_OUT_KIND, SIGNED_OUT_MESSAGE, at=1755700000, resolved_at=1755700100)
    html = _feed([resolved_signed_out])
    assert 'data-code="account.signed_out"' in html, html
    assert "resolved on their own" in html, html


def test_mixed_feed_keeps_only_chat_scope_live():
    live_signed_out = _entry(SIGNED_OUT_KIND, SIGNED_OUT_MESSAGE, at=1755700200)
    live_timeout = _entry(TIMEOUT_KIND, TIMEOUT_MESSAGE, at=1755700100)
    html = _feed([live_signed_out, live_timeout])
    assert 'data-code="rebuild.timeout"' in html, html
    assert 'data-code="account.signed_out"' not in html, html


def test_a_coalesced_entry_shows_count_and_latest_age():
    first_at, last_at, count = 1755700000, 1755700900, 3
    episode = _entry(TIMEOUT_KIND, TIMEOUT_MESSAGE, at=first_at)
    episode["count"] = count
    episode["lastAt"] = last_at
    html = _feed([episode])
    assert f"× {count}" in html, html
    assert f'data-at="{last_at}"' in html, "the card age must track the latest failure"


def test_open_error_summary_picks_the_most_recently_failing_problem():
    quiet_since_start = _entry(SIGNED_OUT_KIND, SIGNED_OUT_MESSAGE, at=1755700500)
    old_but_still_failing = _entry(TIMEOUT_KIND, TIMEOUT_MESSAGE, at=1755700100)
    old_but_still_failing["lastAt"] = 1755700900
    info = serve._open_error_summary([quiet_since_start, old_but_still_failing])
    assert info["openErrors"] == 2, info
    assert info["errorLabel"] == "took too long", info


if __name__ == "__main__":
    run_module_tests(globals())
