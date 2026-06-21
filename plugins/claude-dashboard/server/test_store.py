"""Tests for the unified DashboardStore (recents + regen metrics).
Run with: python3 test_store.py"""

import tempfile
from pathlib import Path

import store


def _store(max_recents=5):
    return store.DashboardStore(Path(tempfile.mkdtemp()) / "dashboard.db", max_recents=max_recents)


# ─── recents ───────────────────────────────────────────────────────────

def test_touch_open_orders_most_recent_first():
    s = _store()
    s.touch_open("-p", "s1")
    s.touch_open("-p", "s2")
    assert [e["session"] for e in s.recents()] == ["s2", "s1"]


def test_touch_open_dedupes_and_bumps_to_front():
    s = _store()
    s.touch_open("-p", "s1")
    s.touch_open("-p", "s2")
    s.touch_open("-p", "s1")  # re-open s1
    r = s.recents()
    assert [e["session"] for e in r] == ["s1", "s2"]
    assert len(r) == 2, "re-open must dedupe, not duplicate"


def test_recents_capped_at_max():
    s = _store(max_recents=3)
    for i in range(6):
        s.touch_open("-p", f"s{i}")
    r = s.recents()
    assert len(r) == 3
    assert [e["session"] for e in r] == ["s5", "s4", "s3"]


def test_forget_open_drops_entry():
    s = _store()
    s.touch_open("-p", "s1")
    s.touch_open("-p", "s2")
    s.forget_open("-p", "s1")
    assert [e["session"] for e in s.recents()] == ["s2"]


# ─── metrics ───────────────────────────────────────────────────────────

def test_record_and_session_summary():
    s = _store()
    sess = "sess-aaa"
    s.record(project_hash="-p", session_uuid=sess, model="sonnet", status="ok",
             input_tokens=100, output_tokens=20, cost_usd=0.01, duration_ms=3000, wall_ms=3200)
    s.record(project_hash="-p", session_uuid=sess, model="sonnet", status="ok",
             input_tokens=50, output_tokens=10, cost_usd=0.005, duration_ms=2000, wall_ms=2100)
    summ = s.session_summary(sess)
    assert summ["regens"] == 2
    assert summ["input_tokens"] == 150
    assert summ["output_tokens"] == 30
    assert abs(summ["cost_usd"] - 0.015) < 1e-9
    assert summ["avg_wall_ms"] == round((3200 + 2100) / 2)
    assert summ["max_wall_ms"] == 3200


def test_failed_rows_excluded_from_ok_summary():
    s = _store()
    sess = "sess-bbb"
    s.record(project_hash="-p", session_uuid=sess, status="ok", input_tokens=10, wall_ms=100)
    s.record(project_hash="-p", session_uuid=sess, status="failed")
    assert s.session_summary(sess)["regens"] == 1, "a failed regen must not count in the ok summary"


def test_totals_across_sessions():
    s = _store()
    s.record(project_hash="-p", session_uuid="s1", status="ok",
             input_tokens=10, output_tokens=2, cost_usd=0.001, wall_ms=100)
    s.record(project_hash="-p", session_uuid="s2", status="ok",
             input_tokens=20, output_tokens=4, cost_usd=0.002, wall_ms=200)
    t = s.totals()
    assert t["regens"] == 2
    assert t["input_tokens"] == 30
    assert t["output_tokens"] == 6


def test_empty_summary_is_zeroed_not_null():
    s = _store()
    summ = s.session_summary("nonexistent")
    assert summ["regens"] == 0
    assert summ["input_tokens"] == 0
    assert summ["cost_usd"] == 0.0


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"\n{len(tests)}/{len(tests)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
