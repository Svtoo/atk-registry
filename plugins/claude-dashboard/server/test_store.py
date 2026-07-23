"""Tests for the unified DashboardStore (recents + regen metrics).
Run with: python3 test_store.py"""

import json
import sqlite3
import tempfile
from pathlib import Path

import store
from testutil import run_module_tests


def _store(max_recents=5):
    return store.DashboardStore(Path(tempfile.mkdtemp()) / "dashboard.db", max_recents=max_recents)


def _last_metric_row(s):
    conn = sqlite3.connect(s._db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute("SELECT * FROM regen_metrics ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        conn.close()


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
    assert summ["models"] == "sonnet", "the summary must name the model(s) used"


def test_summary_lists_each_distinct_model_once():
    s = _store()
    sess = "sess-mixed"
    s.record(project_hash="-p", session_uuid=sess, model="sonnet", status="ok", input_tokens=1, wall_ms=100)
    s.record(project_hash="-p", session_uuid=sess, model="sonnet", status="ok", input_tokens=1, wall_ms=100)
    s.record(project_hash="-p", session_uuid=sess, model="haiku", status="ok", input_tokens=1, wall_ms=100)
    models = s.session_summary(sess)["models"]
    assert sorted(models.split(",")) == ["haiku", "sonnet"], models


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


# ─── telemetry (input size, output size, per-card block sizes, outcome) ──

def test_record_persists_telemetry_fields():
    s = _store()
    words, out_bytes = 7100, 16198
    sizes = {"header": 412, "freeform": 6200, "journey": 2400}
    s.record(project_hash="-p", session_uuid="sess-tel", model="sonnet",
             status="ok", kind="ok", input_tokens=30000, output_tokens=5000,
             wall_ms=39100, prompt_words=words, output_bytes=out_bytes, block_sizes=sizes)
    row = _last_metric_row(s)
    assert row["kind"] == "ok"
    assert row["prompt_words"] == words
    assert row["output_bytes"] == out_bytes
    assert json.loads(row["block_sizes"]) == sizes, "block sizes round-trip as JSON"


def test_record_failure_carries_input_size_and_kind():
    s = _store()
    words = 30912
    s.record(project_hash="-p", session_uuid="sess-to", model="sonnet",
             status="failed", kind="RegenTimeout", prompt_words=words,
             wall_ms=180000, output_bytes=0)
    row = _last_metric_row(s)
    assert row["status"] == "failed" and row["kind"] == "RegenTimeout"
    assert row["prompt_words"] == words
    assert row["block_sizes"] is None, "no block sizes on a failure"


def test_record_omitting_block_sizes_stores_null():
    s = _store()
    s.record(project_hash="-p", session_uuid="sess-nb", status="ok", prompt_words=10)
    assert _last_metric_row(s)["block_sizes"] is None


def test_migration_adds_columns_to_an_existing_db_and_keeps_rows():
    db = Path(tempfile.mkdtemp()) / "dashboard.db"
    v1 = sqlite3.connect(db)
    v1.executescript(
        "CREATE TABLE regen_metrics ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL,"
        " project_hash TEXT NOT NULL, session_uuid TEXT NOT NULL, model TEXT,"
        " status TEXT NOT NULL, input_tokens INTEGER, output_tokens INTEGER,"
        " cost_usd REAL, duration_ms INTEGER, wall_ms INTEGER);"
    )
    v1.execute(
        "INSERT INTO regen_metrics(ts, project_hash, session_uuid, status, input_tokens, wall_ms)"
        " VALUES(1, '-p', 'old-sess', 'ok', 999, 111)"
    )
    v1.commit()
    v1.close()

    s = store.DashboardStore(db)  # opening runs the migration
    probe = sqlite3.connect(db)
    probe.row_factory = sqlite3.Row
    cols = {r["name"] for r in probe.execute("PRAGMA table_info(regen_metrics)")}
    probe.close()
    for c in ("kind", "prompt_words", "output_bytes", "block_sizes", "attempts"):
        assert c in cols, f"migration must add {c}"
    assert s.session_summary("old-sess")["regens"] == 1, "the pre-existing row survives"
    s.record(project_hash="-p", session_uuid="old-sess", status="ok",
             prompt_words=42, block_sizes={"cta": 5})
    assert _last_metric_row(s)["prompt_words"] == 42, "new-field writes work post-migration"


# ─── attempts + stats aggregation ────────────────────────────────────────

def test_record_persists_attempts():
    s = _store()
    tries = 2
    s.record(project_hash="-p", session_uuid="sess-att", status="ok",
             wall_ms=100, attempts=tries)
    assert _last_metric_row(s)["attempts"] == tries


def test_stats_counts_buckets_and_filters_by_since():
    s = _store()
    proj = "-proj"
    recent_ts, old_ts = 2_000, 1_000
    warn_ms = 120_000
    # In-range ok rows: one fast (below the danger band), one slow (inside it).
    s.record(project_hash=proj, session_uuid="s-fast", status="ok",
             input_tokens=10_000, output_tokens=1_500, wall_ms=40_000,
             cost_usd=0.10, attempts=1, ts=recent_ts,
             block_sizes={"freeform": 500, "header": 100})
    s.record(project_hash=proj, session_uuid="s-slow", status="ok",
             input_tokens=90_000, output_tokens=9_000, wall_ms=150_000,
             cost_usd=0.30, attempts=2, ts=recent_ts,
             block_sizes={"freeform": 700, "header": 100})
    # In-range non-ok rows.
    s.record(project_hash=proj, session_uuid="s-fail", status="failed",
             kind="RegenTimeout", ts=recent_ts)
    s.record(project_hash=proj, session_uuid="s-sup", status="superseded",
             kind="SubprocessFailed", ts=recent_ts)
    # Out-of-range ok row (before `since`) must be excluded everywhere.
    s.record(project_hash=proj, session_uuid="s-old", status="ok",
             output_tokens=3_000, wall_ms=60_000, cost_usd=0.99, ts=old_ts)

    st = s.stats(since=recent_ts, warn_ms=warn_ms, bucket="day")

    k = st["kpis"]
    assert k["regens"] == 2, "only the two in-range ok rows count"
    assert k["failed"] == 1
    assert k["superseded"] == 1
    assert k["danger"] == 1, "only s-slow (150s) is past the 120s warn line"
    assert abs(k["cost_usd"] - 0.40) < 1e-9, "the out-of-range row's cost is excluded"

    output_by_label = {b["label"]: b["n"] for b in st["output_buckets"]}
    assert output_by_label["<2k"] == 1, "s-fast (1.5k output) lands in <2k"
    assert output_by_label["8k+"] == 1, "s-slow (9k output) lands in 8k+"

    assert st["blocks"] == {"freeform": 1200, "header": 200}, \
        "per-card bytes are summed across the in-range ok rows"

    attempts_by_n = {a["attempts"]: a["n"] for a in st["attempts"]}
    assert attempts_by_n == {1: 1, 2: 1}

    proj_row = next(p for p in st["by_project"] if p["project"] == proj)
    assert proj_row["regens"] == 2
    assert proj_row["failed"] == 1
    assert proj_row["superseded"] == 1


if __name__ == "__main__":
    run_module_tests(globals())
