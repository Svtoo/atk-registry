"""
Deterministic unit tests for the regen registry's failure handling and
trigger coalescing. No network, no real `claude -p` — run_once is faked so
every path is exercised in-process. Run with: python3 test_regen.py
"""

from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path

import regen

SESS = "sess-test-0001"


def wait_until(pred, timeout: float = 5.0, interval: float = 0.005) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(interval)
    return False


# ─── pure functions ────────────────────────────────────────────────────

def _turn(n_words):
    # one single-event turn whose content carries ~n_words words
    return [{"type": "user", "message": {"role": "user", "content": " ".join(["w"] * n_words)}}]


def test_word_budget_always_keeps_most_recent_turn_even_if_over():
    older = _turn(5000)
    newest = _turn(5000)
    selected, dropped = regen.select_turns_within_word_budget([older, newest], 1000)
    assert selected == [newest], "the most recent turn must always be kept in full"
    assert dropped == 1


def test_word_budget_includes_older_turns_until_full():
    t1, t2, t3 = _turn(300), _turn(300), _turn(300)  # oldest -> newest
    selected, dropped = regen.select_turns_within_word_budget([t1, t2, t3], 700)
    # newest-first: t3 (~302) + t2 (~302) ~= 604 <= 700; adding t1 would exceed -> drop t1
    assert selected == [t2, t3]
    assert dropped == 1


def test_word_budget_zero_disables():
    t1, t2 = _turn(1000), _turn(1000)
    selected, dropped = regen.select_turns_within_word_budget([t1, t2], 0)
    assert selected == [t1, t2]
    assert dropped == 0


def test_render_curated_events_preserves_full_tool_output():
    huge = "z " * 5000
    events = [{"message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": huge},
    ]}}]
    rendered = regen.render_curated_events(events)
    assert "truncated" not in rendered, "render must NOT truncate within a turn"
    assert rendered.count("z") >= 5000, "full tool output must be preserved"


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


def test_parse_cli_json_falls_back_on_non_json():
    raw = "<header>plain html, not the json envelope</header>"
    body, m = regen.parse_cli_json(raw)
    assert body == raw
    assert m == {}


def test_registry_accepts_full_serve_config_kwargs():
    # Regression: serve.py builds Registry with timeout/max_words/metrics, so
    # Registry.__init__ MUST accept exactly those kwargs (a prior version did
    # not, which would crash the server at startup).
    import pathlib
    import tempfile
    d = pathlib.Path(tempfile.mkdtemp())
    reg = regen.Registry(
        plugin_dir=d, projects_root=d,
        model="sonnet", n_turns=6, timeout=180.0, max_words=20000,
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


def test_is_retryable_classifies_transient_vs_structural():
    assert regen._is_retryable(regen.SubprocessFailed("exited 1 socket closed")) is True
    assert regen._is_retryable(regen.FragmentRejected("empty output (first 200 chars: '\\n')")) is True
    assert regen._is_retryable(regen.FragmentRejected("output too small (123 bytes)")) is True
    structural = regen.FragmentRejected("missing required marker '<div class=\"pills\">'")
    assert regen._is_retryable(structural) is False
    assert regen._is_retryable(FileNotFoundError("jsonl gone")) is False


# ─── registry: retry behaviour ─────────────────────────────────────────

def _registry(on_failure=None, on_success=None):
    return regen.Registry(
        plugin_dir=Path("."),
        projects_root=Path("."),
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


def test_structural_rejection_does_not_retry(monkeypatched):
    calls = []

    def fake(**kw):
        calls.append(1)
        raise regen.FragmentRejected("missing required marker '<div class=\"pills\">'")

    monkeypatched(fake)
    failures = []
    reg = _registry(on_failure=lambda *a: failures.append(a))
    reg.trigger("hash", SESS)
    assert wait_until(lambda: len(failures) == 1), "structural failure must surface"
    assert len(calls) == 1, f"structural failure must surface on first attempt, got {len(calls)}"
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
