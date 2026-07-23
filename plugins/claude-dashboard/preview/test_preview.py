#!/usr/bin/env python3
"""Tests for session_open.py — the once-per-session UserPromptSubmit hook that
tells the agent to open this chat's dashboard URL in the Browser pane.
Run: python3 test_preview.py
"""
import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "server"))
import session_open  # noqa: E402
from testutil import run_module_tests  # noqa: E402


# ── server port ────────────────────────────────────────────────────────

def test_server_port_reads_marker_file():
    with tempfile.TemporaryDirectory() as d:
        plugin = Path(d)
        (plugin / "runtime").mkdir()
        bound_port = 7878
        (plugin / "runtime" / "port").write_text(f"{bound_port}\n")
        assert session_open.server_port(plugin) == bound_port


def test_server_port_falls_back_when_marker_missing():
    with tempfile.TemporaryDirectory() as d:
        assert session_open.server_port(Path(d)) == session_open.DEFAULT_PORT


def test_server_port_reads_a_non_default_override():
    with tempfile.TemporaryDirectory() as d:
        plugin = Path(d)
        (plugin / "runtime").mkdir()
        override = 9191
        (plugin / "runtime" / "port").write_text(str(override))
        assert session_open.server_port(plugin) == override


# ── dashboard URL ──────────────────────────────────────────────────────

def test_dashboard_url_from_transcript_uses_bound_port():
    with tempfile.TemporaryDirectory() as d:
        plugin = Path(d)
        (plugin / "runtime").mkdir()
        bound_port = 7878
        (plugin / "runtime" / "port").write_text(str(bound_port))
        proj_hash = "-Users-x--atk"
        session = "164d45f8-uuid"
        transcript = f"/Users/x/.claude/projects/{proj_hash}/{session}.jsonl"
        actual = session_open.dashboard_url(transcript, plugin)
        assert actual == f"http://localhost:{bound_port}/{proj_hash}/{session}/dashboard.html"


def test_dashboard_url_empty_transcript_is_none():
    with tempfile.TemporaryDirectory() as d:
        assert session_open.dashboard_url("", Path(d)) is None


# ── the injected instruction ───────────────────────────────────────────

def test_open_instruction_carries_url_and_reopen_capability():
    url = "http://localhost:7878/-Users-x--atk/sid/dashboard.html"
    ctx = session_open.open_instruction(url)
    assert url in ctx
    assert "preview_start" in ctx
    assert "<system-reminder>" in ctx and "</system-reminder>" in ctx
    assert "reopen" in ctx.lower(), "the agent must know it can reopen on request"
    # never hardcode an MCP server name
    assert "Claude_Preview" not in ctx


# ── main() ─────────────────────────────────────────────────────────────

def _run_main(plugin_dir, payload):
    out = io.StringIO()
    old_stdin = sys.stdin
    os.environ["DASHBOARD_PLUGIN_DIR"] = str(plugin_dir)
    try:
        sys.stdin = io.StringIO(json.dumps(payload))
        with contextlib.redirect_stdout(out):
            session_open.main()
    finally:
        sys.stdin = old_stdin
        os.environ.pop("DASHBOARD_PLUGIN_DIR", None)
    return out.getvalue()


def _userprompt_payload(cwd, session_id="sess-1"):
    return {
        "hook_event_name": "UserPromptSubmit",
        "session_id": session_id,
        "transcript_path": f"/home/projects/-Users-x--atk/{session_id}.jsonl",
        "cwd": str(cwd),
    }


def test_main_injects_once_and_writes_nothing_to_the_project():
    with tempfile.TemporaryDirectory() as d:
        plugin_dir = Path(d) / "plugin"
        cwd = Path(d) / "proj"
        cwd.mkdir(parents=True)
        session_id = "sess-A"

        first = _run_main(plugin_dir, _userprompt_payload(cwd, session_id))
        ctx = json.loads(first)["hookSpecificOutput"]["additionalContext"]
        expected_url = f"http://localhost:{session_open.DEFAULT_PORT}/-Users-x--atk/{session_id}/dashboard.html"
        assert expected_url in ctx
        assert not (cwd / ".claude").exists(), "the hook writes nothing to the project"
        assert session_open.opened_marker(plugin_dir, session_id).exists()

        second = _run_main(plugin_dir, _userprompt_payload(cwd, session_id))
        assert second.strip() == "", repr(second)


def test_main_silent_on_non_userpromptsubmit_event():
    with tempfile.TemporaryDirectory() as d:
        plugin_dir = Path(d) / "plugin"
        cwd = Path(d) / "proj"
        cwd.mkdir(parents=True)
        payload = _userprompt_payload(cwd, "sess-C")
        payload["hook_event_name"] = "SessionStart"
        out = _run_main(plugin_dir, payload)
        assert out.strip() == "", repr(out)
        assert not (cwd / ".claude").exists()


def test_main_survives_non_dict_payload():
    with tempfile.TemporaryDirectory() as d:
        plugin_dir = Path(d) / "plugin"
        for bad in ([1, 2, 3], "a string", 42):
            out = _run_main(plugin_dir, bad)
            assert out.strip() == "", repr((bad, out))


def test_preview_enabled_default_env_and_dotenv():
    with tempfile.TemporaryDirectory() as d:
        plugin = Path(d)
        assert session_open.preview_enabled(plugin) is True
        for v in ("false", "0", "no", "off", "Disabled"):
            os.environ["CCD_PREVIEW_PANE"] = v
            try:
                assert session_open.preview_enabled(plugin) is False, v
            finally:
                os.environ.pop("CCD_PREVIEW_PANE", None)
        os.environ["CCD_PREVIEW_PANE"] = "true"
        try:
            assert session_open.preview_enabled(plugin) is True
        finally:
            os.environ.pop("CCD_PREVIEW_PANE", None)
        (plugin / ".env").write_text("CCD_MODEL=sonnet\nCCD_PREVIEW_PANE=false\n")
        assert session_open.preview_enabled(plugin) is False


def test_preview_enabled_survives_non_utf8_env():
    with tempfile.TemporaryDirectory() as d:
        plugin = Path(d)
        corrupt = b"CCD_PREVIEW_PANE=\xff\xfe true\n"
        (plugin / ".env").write_bytes(corrupt)
        assert "CCD_PREVIEW_PANE" not in os.environ
        assert session_open.preview_enabled(plugin) is True


def test_main_noop_when_preview_disabled():
    with tempfile.TemporaryDirectory() as d:
        plugin_dir = Path(d) / "plugin"
        cwd = Path(d) / "proj"
        cwd.mkdir(parents=True)
        os.environ["CCD_PREVIEW_PANE"] = "false"
        try:
            out = _run_main(plugin_dir, _userprompt_payload(cwd, "sess-D"))
        finally:
            os.environ.pop("CCD_PREVIEW_PANE", None)
        assert out.strip() == "", repr(out)


if __name__ == "__main__":
    run_module_tests(globals())
