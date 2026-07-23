"""
Deterministic unit tests for the regen registry's failure handling and
trigger coalescing. No network, no real `claude -p` — run_once is faked so
every path is exercised in-process. Run with: python3 test_regen.py
"""

from __future__ import annotations

import sqlite3
import tempfile
import threading
import time
from pathlib import Path

import regen
import store

SESS = "sess-test-0001"


def wait_until(pred, timeout: float = 5.0, interval: float = 0.005) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(interval)
    return False


def test_regen_timeout_is_not_retryable_but_subprocessfailed_is():
    timeout_err = regen.RegenTimeout("claude -p exceeded 180s wall-clock")
    transient_err = regen.SubprocessFailed("streaming socket closed")
    assert regen._is_retryable(timeout_err) is False
    assert regen._is_retryable(transient_err) is True


def test_parse_cli_json_extracts_result_and_usage():
    import json as _json
    envelope = _json.dumps({
        "result": "<header class='session-header'></header>",
        "usage": {
            "input_tokens": 10, "cache_creation_input_tokens": 7271,
            "cache_read_input_tokens": 0, "output_tokens": 41,
        },
        "total_cost_usd": 0.0098, "duration_ms": 3174,
    })
    body, m = regen.parse_cli_json(envelope)
    assert body == "<header class='session-header'></header>"
    assert m["input_tokens"] == 10 + 7271 + 0
    assert m["output_tokens"] == 41
    assert m["cost_usd"] == 0.0098
    assert m["duration_ms"] == 3174
    assert m["model"] is None, "no modelUsage block means no resolved model"


def test_parse_cli_json_resolves_the_generating_model():
    # The CLI envelope names the exact models used; the metrics must record
    # the resolved id (which generation model an alias mapped to), picking the
    # one that did the work over the CLI's tiny internal helper calls.
    import json as _json
    main_model = "claude-sonnet-4-6"
    envelope = _json.dumps({
        "result": "{}",
        "usage": {"input_tokens": 10, "output_tokens": 22},
        "modelUsage": {
            "claude-haiku-4-5-20251001": {"inputTokens": 504, "outputTokens": 11},
            main_model: {"inputTokens": 10, "outputTokens": 22,
                         "cacheCreationInputTokens": 7275},
        },
    })
    _, m = regen.parse_cli_json(envelope)
    assert m["model"] == main_model, m["model"]


def test_parse_cli_json_falls_back_on_non_json():
    raw = "<header>plain html, not the json envelope</header>"
    body, m = regen.parse_cli_json(raw)
    assert body == raw
    assert m == {}


def test_registry_accepts_full_serve_config_kwargs():
    # Regression: serve.py builds Registry with exactly these kwargs, so
    # Registry.__init__ MUST accept them (a mismatch crashes the server at startup).
    import pathlib
    import tempfile
    d = pathlib.Path(tempfile.mkdtemp())
    reg = regen.Registry(
        plugin_dir=d, projects_root=d, chat_state=None,
        model="sonnet", timeout=180.0,
        metrics=None, on_success=None, on_failure=None,
    )
    assert reg is not None


def test_atomic_write_creates_file_and_leaves_no_tmp():
    d = Path(tempfile.mkdtemp())
    body = '<header class="session-header">x</header>' + "y" * 600
    regen.atomic_write(d, body)
    actual = (d / "dashboard.html").read_text()
    assert actual == body, "written content must round-trip"
    leftovers = list(d.glob("*.tmp")) + list(d.glob(".dashboard.*"))
    assert leftovers == [], f"no stray tmp expected, found {leftovers}"
    body2 = body + "z"
    regen.atomic_write(d, body2)
    assert (d / "dashboard.html").read_text() == body2, "overwrite must succeed"


def test_a_failure_that_would_repeat_is_not_retried():
    # Retrying re-sends the identical prompt, so an oversized prompt fails the
    # same way and an expired sign in is still expired. Both burned a second
    # `claude -p` call for nothing.
    too_long = regen.SubprocessFailed(
        "claude -p exited 1 after 1.1s\n--- stdout ---\nPrompt is too long")
    expired = regen.SubprocessFailed(
        "claude -p exited 1\n--- stdout ---\n"
        "Failed to authenticate. API Error: 401 OAuth access token has expired.")
    assert regen._is_retryable(too_long) is False, "an oversized prompt must not be retried"
    assert regen._is_retryable(expired) is False, "an expired sign in must not be retried"


def test_retry_instruction_names_the_format_the_parser_accepts():
    # agent_io.parse_output reads <update> and <freeform ref="…"> blocks; a
    # retry hint naming any other format makes the corrective retry re-fail.
    assert "<update>" in regen.RETRY_INSTRUCTION
    assert "<freeform" in regen.RETRY_INSTRUCTION
    assert "```" not in regen.RETRY_INSTRUCTION


def test_is_retryable_classifies_transient_vs_rejected():
    # OutputRejected already consumed run_once's corrective retry; only
    # transient subprocess failures earn a registry-level second attempt.
    assert regen._is_retryable(regen.SubprocessFailed("exited 1 socket closed")) is True
    assert regen._is_retryable(regen.OutputRejected("op-set invalid after retry: bad json")) is False
    assert regen._is_retryable(regen.OutputRejected("render too small (12 bytes)")) is False
    assert regen._is_retryable(FileNotFoundError("jsonl gone")) is False


# ─── registry: retry behaviour ─────────────────────────────────────────

def _registry(on_failure=None, on_success=None):
    # chat_state=None is fine here: every registry test fakes run_once, so
    # nothing dereferences it.
    return regen.Registry(
        plugin_dir=Path("."),
        projects_root=Path("."),
        chat_state=None,
        on_failure=on_failure,
        on_success=on_success,
    )


def test_transient_failure_is_retried_then_succeeds(monkeypatched):
    calls = []

    def fake(**kw):
        calls.append(1)
        if len(calls) == 1:
            raise regen.SubprocessFailed("claude -p exited 1 — socket closed")
        return Path("/tmp/ok")

    monkeypatched(fake)
    failures = []
    reg = _registry(on_failure=lambda *a: failures.append(a))
    reg.trigger("hash", SESS)
    assert wait_until(lambda: reg.state_for(SESS) is None), "success clears the record"
    assert len(calls) == 2, f"one retry expected, got {len(calls)} attempts"
    assert failures == [], "a recovered transient must NOT surface an error"


def test_retries_are_bounded_then_error_surfaces(monkeypatched):
    calls = []

    def fake(**kw):
        calls.append(1)
        raise regen.SubprocessFailed("persistent boom")

    monkeypatched(fake)
    failures = []
    reg = _registry(on_failure=lambda *a: failures.append(a))
    reg.trigger("hash", SESS)
    # Wait on the on_failure callback — it fires AFTER state flips to
    # "failed" (which happens under the lock), so it is the settled signal.
    assert wait_until(lambda: len(failures) == 1), "surface exactly one error after retries exhaust"
    assert len(calls) == regen.MAX_ATTEMPTS, f"must stop at MAX_ATTEMPTS, got {len(calls)}"
    s = reg.state_for(SESS)
    assert s is not None and s["state"] == "failed", f"record should be failed, got {s}"


def test_output_rejection_does_not_retry(monkeypatched):
    calls = []

    def fake(**kw):
        calls.append(1)
        raise regen.OutputRejected("op-set invalid after retry: not valid JSON")

    monkeypatched(fake)
    failures = []
    reg = _registry(on_failure=lambda *a: failures.append(a))
    reg.trigger("hash", SESS)
    assert wait_until(lambda: len(failures) == 1), "a rejected output must surface"
    assert len(calls) == 1, f"a rejected output must surface on first attempt, got {len(calls)}"
    s = reg.state_for(SESS)
    assert s is not None and s["state"] == "failed", f"record should be failed, got {s}"


# ─── registry: trigger coalescing ──────────────────────────────────────

def test_concurrent_trigger_coalesces_into_single_rerun(monkeypatched):
    gate = threading.Event()
    started = threading.Event()
    calls = []

    def fake(**kw):
        calls.append(1)
        started.set()
        gate.wait(3)
        return Path("/tmp/ok")

    monkeypatched(fake)
    reg = _registry()
    reg.trigger("hash", SESS)
    assert started.wait(3), "first run should start"
    # Trigger again while the first is in flight: must coalesce, not spawn.
    snap = reg.trigger("hash", SESS)
    assert snap["state"] == "running", f"coalesced trigger returns running, got {snap}"
    assert len(calls) == 1, f"no concurrent second run allowed, got {len(calls)}"
    gate.set()  # let the first finish → exactly one queued rerun fires
    assert wait_until(lambda: len(calls) == 2, timeout=3), f"coalesced rerun should run, calls={len(calls)}"
    assert wait_until(lambda: reg.state_for(SESS) is None, timeout=3), "rerun should finish"
    time.sleep(0.05)
    assert len(calls) == 2, f"no third run — the rerun is consumed once, got {len(calls)}"


def test_quiet_completion_does_not_rerun(monkeypatched):
    calls = []

    def fake(**kw):
        calls.append(1)
        return Path("/tmp/ok")

    monkeypatched(fake)
    reg = _registry()
    reg.trigger("hash", SESS)
    assert wait_until(lambda: reg.state_for(SESS) is None)
    time.sleep(0.05)
    assert len(calls) == 1, f"no trigger arrived mid-run → exactly one run, got {len(calls)}"


# ─── registry: supersede telemetry ─────────────────────────────────────

def test_superseded_run_records_a_superseded_row(monkeypatched):
    st = store.DashboardStore(Path(tempfile.mkdtemp()) / "dashboard.db")

    def fake(**kw):
        # A SIGTERM landing mid-flight: the registry has marked this job
        # superseded, and the killed subprocess surfaces as SubprocessFailed.
        reg._jobs[SESS].superseded = True
        raise regen.SubprocessFailed("claude -p killed by supersede")

    monkeypatched(fake)
    reg = regen.Registry(
        plugin_dir=Path("."), projects_root=Path("."), chat_state=None, metrics=st,
    )
    reg.trigger("hash", SESS)
    assert wait_until(lambda: st.stats(since=0)["kpis"]["superseded"] == 1), \
        "a superseded run records exactly one superseded row"
    kpis = st.stats(since=0)["kpis"]
    assert kpis["failed"] == 0, "a supersede is not a failure"
    assert kpis["regens"] == 0, "a supersede is not an ok regen"

    conn = sqlite3.connect(st._db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT status, kind, attempts FROM regen_metrics ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    assert row["status"] == "superseded"
    assert row["kind"] == "SubprocessFailed"
    assert row["attempts"] == 1, "the attempt number at the kill is recorded"


# ─── auth policy + health probe ────────────────────────────────────────

class _FakePopen:
    def __init__(self, rc=0, out="", err=""):
        self.returncode = rc
        self._out = out
        self._err = err

    def communicate(self, input=None, timeout=None):
        return self._out, self._err

    def kill(self):
        pass


def test_build_subagent_env_strips_ambient_api_keys():
    import os
    # Every var here hijacks `claude -p` auth if it leaks into the server's
    # environment: API_KEY/AUTH_TOKEN divert to API-key billing; BASE_URL
    # redirects the subscription OAuth to a proxy (e.g. Claude Code's own
    # endpoint when the server is started from a Claude Code shell) which
    # rejects the credentials with a 401. All must be stripped.
    poison = {
        "ANTHROPIC_API_KEY": "sk-dead",
        "ANTHROPIC_AUTH_TOKEN": "tok-dead",
        "ANTHROPIC_BASE_URL": "http://localhost:9999/leaked-proxy",
    }
    saved = {k: os.environ.get(k) for k in poison}
    try:
        os.environ.update(poison)
        env = regen.build_subagent_env()
        for var in poison:
            assert var not in env, f"{var} must be stripped from subagent env"
        assert env[regen.SUBAGENT_ENV_MARKER] == "1", "subagent marker must be set"
        assert os.environ["ANTHROPIC_API_KEY"] == poison["ANTHROPIC_API_KEY"], \
            "real os.environ must be untouched"
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_probe_auth_ok_when_cli_returns_text():
    original = regen.subprocess.Popen
    try:
        regen.subprocess.Popen = lambda *a, **k: _FakePopen(rc=0, out="ok\n")
        ok, detail = regen.probe_auth()
        assert ok is True, "exit 0 + non-empty stdout means healthy"
        assert "ok" in detail
    finally:
        regen.subprocess.Popen = original


def test_probe_auth_reports_credit_failure():
    credit_msg = "Credit balance is too low"
    original = regen.subprocess.Popen
    try:
        regen.subprocess.Popen = lambda *a, **k: _FakePopen(rc=1, out=credit_msg)
        ok, detail = regen.probe_auth()
        assert ok is False, "non-zero exit means unhealthy"
        assert credit_msg in detail, "the CLI's own diagnostic must surface"
    finally:
        regen.subprocess.Popen = original


# ─── registry: vanished-session skip + subprocess cleanup ──────────────

def test_run_once_raises_session_gone_when_jsonl_missing():
    # A chat deleted (or its git worktree cleaned) between the regen trigger and
    # the worker running leaves no <uuid>.jsonl. That is "gone", NOT a failure —
    # run_once must signal it distinctly so the registry can skip it quietly,
    # while a missing SYSTEM.md (broken config) stays a real, surfaced error.
    uuid = "deadbeef-0000-0000-0000-000000000000"

    # (a) jsonl missing, SYSTEM.md present → SessionGone
    d = Path(tempfile.mkdtemp())
    (d / "SYSTEM.md").write_text("system prompt")
    try:
        regen.run_once(plugin_dir=d, projects_root=d,
                       project_hash="-proj", session_uuid=uuid, chat_state=None)
        raise AssertionError("expected SessionGone when the jsonl is missing")
    except regen.SessionGone:
        pass  # correct

    # (b) jsonl present, SYSTEM.md missing → a real error, NOT SessionGone
    d2 = Path(tempfile.mkdtemp())
    (d2 / "-proj").mkdir()
    (d2 / "-proj" / f"{uuid}.jsonl").write_text("{}")
    try:
        regen.run_once(plugin_dir=d2, projects_root=d2,
                       project_hash="-proj", session_uuid=uuid, chat_state=None)
        raise AssertionError("expected an error when SYSTEM.md is missing")
    except regen.SessionGone:
        raise AssertionError("missing SYSTEM.md must NOT be classified as SessionGone")
    except FileNotFoundError:
        pass  # correct — broken config surfaces as a real error


def test_vanished_session_is_skipped_not_surfaced(monkeypatched):
    # When run_once reports the session is gone, the registry must drop the job
    # quietly: no on_failure banner, and no lingering "failed" record.
    def fake(**kw):
        raise regen.SessionGone("jsonl not found")

    monkeypatched(fake)
    failures = []
    reg = _registry(on_failure=lambda *a: failures.append(a))
    reg.trigger("hash", SESS)
    assert wait_until(lambda: reg.state_for(SESS) is None), "skipped job clears its record"
    time.sleep(0.05)
    assert failures == [], "a vanished session must NOT surface an error banner"


class _RaisingPopen:
    """Popen stub whose communicate() raises a non-timeout error on the first
    call (the real generation) and reaps cleanly once killed."""

    def __init__(self, exc):
        self._exc = exc
        self.returncode = None
        self.killed = False

    def communicate(self, input=None, timeout=None):
        if not self.killed:
            raise self._exc
        return "", ""  # post-kill reap

    def kill(self):
        self.killed = True


def test_invoke_claude_kills_subprocess_on_non_timeout_error():
    # If communicate() raises anything other than TimeoutExpired, the child must
    # still be killed before the error propagates — otherwise the `claude -p`
    # process leaks.
    boom = ValueError("stream pipe broke")
    fake = _RaisingPopen(boom)
    original = regen.subprocess.Popen
    try:
        regen.subprocess.Popen = lambda *a, **k: fake
        raised = None
        try:
            regen.invoke_claude(system_prompt="s", user_message="m",
                                model="sonnet", timeout=5.0)
        except ValueError as e:
            raised = e
        assert raised is boom, "the original error must propagate"
        assert fake.killed, "the subprocess must be killed so it does not leak"
    finally:
        regen.subprocess.Popen = original


# ─── runner ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import traceback

    def make_monkeypatched():
        """Returns (apply_fn, restore_fn): apply swaps regen.run_once,
        restore puts the original back so tests don't leak into each other."""
        original = regen.run_once
        state = {"applied": False}

        def apply(fn):
            regen.run_once = fn
            state["applied"] = True

        def restore():
            regen.run_once = original

        return apply, restore

    tests = [
        v for k, v in sorted(globals().items())
        if k.startswith("test_") and callable(v)
    ]
    failed = 0
    for t in tests:
        apply, restore = make_monkeypatched()
        try:
            if t.__code__.co_argcount == 1:
                t(apply)
            else:
                t()
            print(f"PASS {t.__name__}")
        except Exception as e:
            failed += 1
            traceback.print_exc()
            print(f"FAIL {t.__name__}: {e}")
        finally:
            restore()
    total = len(tests)
    print(f"\n{total - failed}/{total} passed")
    sys.exit(1 if failed else 0)
