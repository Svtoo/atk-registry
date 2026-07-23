"""SQLite store for the dashboard server's runtime data (runtime/dashboard.db).

recents: server-global most-recently-opened (project, session) queue.
regen_metrics: one row per regeneration attempt (tokens, cost, latency, outcome).

Per-chat state (acks, errors, the dashboard model) lives with each chat via
chat_state.ChatState, not here. Writes are best-effort: a failed write never
blocks a regen.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from logging_config import get_logger

_log = get_logger("store")

# Telemetry columns applied by _migrate.
_TELEMETRY_COLUMNS = {
    "kind":         "TEXT",     # ok | RegenTimeout | OutputRejected | SubprocessFailed
    "prompt_words": "INTEGER",  # assembled prompt size (estimate_words)
    "output_bytes": "INTEGER",  # rendered dashboard bytes, or partial bytes at a timeout kill
    "block_sizes":  "TEXT",     # JSON {card: bytes} of the rendered cards
    "attempts":     "INTEGER",  # job-level tries spent before this row's outcome (1 = first try)
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS recents (
    project_hash  TEXT NOT NULL,
    session_uuid  TEXT NOT NULL,
    opened_at     REAL NOT NULL,
    PRIMARY KEY (project_hash, session_uuid)
);
CREATE INDEX IF NOT EXISTS idx_recents_opened ON recents(opened_at);

CREATE TABLE IF NOT EXISTS regen_metrics (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            INTEGER NOT NULL,
    project_hash  TEXT NOT NULL,
    session_uuid  TEXT NOT NULL,
    model         TEXT,
    status        TEXT NOT NULL,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    cost_usd      REAL,
    duration_ms   INTEGER,
    wall_ms       INTEGER
);
CREATE INDEX IF NOT EXISTS idx_metrics_session ON regen_metrics(session_uuid);
CREATE INDEX IF NOT EXISTS idx_metrics_ts ON regen_metrics(ts);
"""


# Upper edges (exclusive) and labels for the output/input-vs-wall breakdowns on
# the stats page. The final bucket (edge None) is open-ended.
_OUTPUT_BUCKETS = [(2000, "<2k"), (4000, "2–4k"), (6000, "4–6k"), (8000, "6–8k"), (None, "8k+")]
_INPUT_BUCKETS = [(20000, "<20k"), (40000, "20–40k"), (60000, "40–60k"), (80000, "60–80k"), (None, "80k+")]


def _bucketize(rows: "list[tuple]", edges: "list[tuple]") -> "list[dict]":
    """rows: (value, wall_ms) pairs. Returns per-bucket count and avg wall seconds
    in edge order; a None value is skipped."""
    counts = [0] * len(edges)
    wall_sum = [0.0] * len(edges)
    wall_n = [0] * len(edges)
    for value, wall in rows:
        if value is None:
            continue
        for i, (edge, _) in enumerate(edges):
            if edge is None or value < edge:
                counts[i] += 1
                if wall is not None:
                    wall_sum[i] += wall
                    wall_n[i] += 1
                break
    out = []
    for i, (_, label) in enumerate(edges):
        avg = round(wall_sum[i] / wall_n[i] / 1000.0, 1) if wall_n[i] else None
        out.append({"label": label, "n": counts[i], "avg_wall_s": avg})
    return out


class DashboardStore:
    """Server-global recents queue + historical regen metrics in one SQLite db."""

    def __init__(self, db_path: Path, *, max_recents: int = 5):
        self._db_path = Path(db_path)
        self._max_recents = max_recents
        self._lock = threading.Lock()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        # Schema init must fail loudly, not swallow errors the way _db does.
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(_SCHEMA)
                self._migrate(conn)
                conn.commit()
            finally:
                conn.close()

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Add any regen_metrics column not already present. Idempotent."""
        have = {row["name"] for row in conn.execute("PRAGMA table_info(regen_metrics)")}
        for col, decl in _TELEMETRY_COLUMNS.items():
            if col not in have:
                conn.execute(f"ALTER TABLE regen_metrics ADD COLUMN {col} {decl}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _db(self, op: str):
        """One locked connection per op; commit on success, log and swallow sqlite errors."""
        with self._lock:
            conn = self._connect()
            try:
                yield conn
                conn.commit()
            except sqlite3.Error as e:
                _log.warning("store: %s failed: %s", op, e)
            finally:
                conn.close()

    # ─── Recents (server-global, most-recently-opened first, capped) ──

    def touch_open(self, project_hash: str, session_uuid: str) -> None:
        now = time.time()  # sub-second, for stable ordering of rapid opens
        with self._db("touch_open") as conn:
            conn.execute(
                "INSERT INTO recents(project_hash, session_uuid, opened_at) "
                "VALUES(?, ?, ?) "
                "ON CONFLICT(project_hash, session_uuid) "
                "DO UPDATE SET opened_at=excluded.opened_at",
                (project_hash, session_uuid, now),
            )
            # Keep only the N most recent.
            conn.execute(
                "DELETE FROM recents WHERE rowid NOT IN "
                "(SELECT rowid FROM recents ORDER BY opened_at DESC LIMIT ?)",
                (self._max_recents,),
            )

    def recents(self) -> "list[dict]":
        rows: list = []
        with self._db("recents") as conn:
            rows = conn.execute(
                "SELECT project_hash, session_uuid, opened_at FROM recents "
                "ORDER BY opened_at DESC LIMIT ?",
                (self._max_recents,),
            ).fetchall()
        return [
            {"project": r["project_hash"], "session": r["session_uuid"],
             "openedAt": int(r["opened_at"])}
            for r in rows
        ]

    def forget_open(self, project_hash: str, session_uuid: str) -> None:
        with self._db("forget_open") as conn:
            conn.execute(
                "DELETE FROM recents WHERE project_hash=? AND session_uuid=?",
                (project_hash, session_uuid),
            )

    # ─── Regen metrics (historical, all sessions) ─────────────────────

    def record(
        self,
        *,
        project_hash: str,
        session_uuid: str,
        model: "str | None" = None,
        status: str = "ok",
        kind: "str | None" = None,
        input_tokens: "int | None" = None,
        output_tokens: "int | None" = None,
        cost_usd: "float | None" = None,
        duration_ms: "int | None" = None,
        wall_ms: "int | None" = None,
        prompt_words: "int | None" = None,
        output_bytes: "int | None" = None,
        block_sizes: "dict | None" = None,
        attempts: "int | None" = None,
        ts: "int | None" = None,
    ) -> None:
        ts = int(ts if ts is not None else time.time())
        blocks_json = json.dumps(block_sizes, separators=(",", ":")) if block_sizes else None
        with self._db("record") as conn:
            conn.execute(
                "INSERT INTO regen_metrics"
                "(ts, project_hash, session_uuid, model, status, kind, input_tokens,"
                " output_tokens, cost_usd, duration_ms, wall_ms, prompt_words,"
                " output_bytes, block_sizes, attempts)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ts, project_hash, session_uuid, model, status, kind,
                 input_tokens, output_tokens, cost_usd, duration_ms, wall_ms,
                 prompt_words, output_bytes, blocks_json, attempts),
            )

    def session_summary(self, session_uuid: str) -> dict:
        return self._summary("WHERE session_uuid=? AND status='ok'", (session_uuid,))

    def totals(self) -> dict:
        return self._summary("WHERE status='ok'", ())

    def _summary(self, where: str, params: tuple) -> dict:
        row = None
        with self._db("summary") as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS regens,"
                " COALESCE(SUM(input_tokens),0) AS input_tokens,"
                " COALESCE(SUM(output_tokens),0) AS output_tokens,"
                " COALESCE(SUM(cost_usd),0.0) AS cost_usd,"
                " AVG(wall_ms) AS avg_wall_ms,"
                " MAX(wall_ms) AS max_wall_ms,"
                " GROUP_CONCAT(DISTINCT model) AS models"
                f" FROM regen_metrics {where}",
                params,
            ).fetchone()
        d = dict(row) if row else {}
        if d.get("avg_wall_ms") is not None:
            d["avg_wall_ms"] = round(d["avg_wall_ms"])
        return d

    def failure_row(self, session_uuid: str, at: int, window_s: int = 180) -> dict:
        """Measurements for the rebuild that failed at roughly `at`, used to
        describe a failure without touching anything from the conversation.
        Numbers only; the caller decides which are safe to show."""
        row = None
        with self._db("failure_row") as conn:
            row = conn.execute(
                "SELECT ts, model, kind, input_tokens, output_tokens, duration_ms,"
                " wall_ms, prompt_words, output_bytes, attempts"
                " FROM regen_metrics"
                " WHERE session_uuid=? AND status!='ok' AND ABS(ts-?)<=?"
                " ORDER BY ABS(ts-?) LIMIT 1",
                (session_uuid, at, window_s, at),
            ).fetchone()
        return dict(row) if row else {}

    def stats(self, *, since: int = 0, warn_ms: "int | None" = None,
              bucket: str = "day") -> dict:
        """Aggregate regen_metrics from `since` (unix seconds; 0 = all history) for
        the stats page: KPIs, output/input-vs-wall buckets, per-card byte shares,
        per-project and over-time rollups, failure kinds, retry/supersede counts.
        `warn_ms` marks the timeout danger band; `bucket` is 'day' or 'hour'."""
        fmt = "%Y-%m-%dT%H:00" if bucket == "hour" else "%Y-%m-%d"
        ok: list = []
        status_rows: list = []
        by_project: list = []
        series: list = []
        kinds: list = []
        with self._db("stats") as conn:
            ok = conn.execute(
                "SELECT input_tokens, output_tokens, wall_ms, cost_usd, attempts,"
                " block_sizes FROM regen_metrics WHERE status='ok' AND ts>=?",
                (since,),
            ).fetchall()
            status_rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM regen_metrics WHERE ts>=?"
                " GROUP BY status",
                (since,),
            ).fetchall()
            by_project = conn.execute(
                "SELECT project_hash,"
                " SUM(status='ok') AS regens,"
                " SUM(status='failed') AS failed,"
                " SUM(status='superseded') AS superseded,"
                " AVG(CASE WHEN status='ok' THEN wall_ms END) AS avg_wall_ms,"
                " COALESCE(SUM(CASE WHEN status='ok' THEN cost_usd END),0.0) AS cost_usd"
                " FROM regen_metrics WHERE ts>=? GROUP BY project_hash"
                " ORDER BY regens DESC",
                (since,),
            ).fetchall()
            series = conn.execute(
                f"SELECT strftime('{fmt}', ts, 'unixepoch', 'localtime') AS t,"
                " SUM(status='ok') AS regens,"
                " AVG(CASE WHEN status='ok' THEN wall_ms END) AS avg_wall_ms,"
                " COALESCE(SUM(CASE WHEN status='ok' THEN cost_usd END),0.0) AS cost_usd"
                " FROM regen_metrics WHERE ts>=? GROUP BY t ORDER BY t",
                (since,),
            ).fetchall()
            kinds = conn.execute(
                "SELECT COALESCE(kind,'not recorded') AS kind, COUNT(*) AS n"
                " FROM regen_metrics WHERE status='failed' AND ts>=?"
                " GROUP BY kind ORDER BY n DESC",
                (since,),
            ).fetchall()

        cost = sum(r["cost_usd"] or 0.0 for r in ok)
        walls = [r["wall_ms"] for r in ok if r["wall_ms"] is not None]
        danger = (
            sum(1 for w in walls if w >= warn_ms) if warn_ms is not None else None
        )
        blocks: dict = {}
        for r in ok:
            if not r["block_sizes"]:
                continue
            try:
                for card, size in json.loads(r["block_sizes"]).items():
                    blocks[card] = blocks.get(card, 0) + size
            except (ValueError, TypeError):
                continue
        attempts: dict = {}
        for r in ok:
            a = r["attempts"]
            if a is not None:
                attempts[a] = attempts.get(a, 0) + 1
        status_counts = {r["status"]: r["n"] for r in status_rows}

        return {
            "kpis": {
                "regens": len(ok),
                "failed": status_counts.get("failed", 0),
                "superseded": status_counts.get("superseded", 0),
                "cost_usd": round(cost, 2),
                "avg_wall_s": round(sum(walls) / len(walls) / 1000.0, 1) if walls else None,
                "danger": danger,
            },
            "output_buckets": _bucketize(
                [(r["output_tokens"], r["wall_ms"]) for r in ok], _OUTPUT_BUCKETS),
            "input_buckets": _bucketize(
                [(r["input_tokens"], r["wall_ms"]) for r in ok], _INPUT_BUCKETS),
            "blocks": blocks,
            "by_project": [
                {"project": r["project_hash"], "regens": r["regens"] or 0,
                 "failed": r["failed"] or 0, "superseded": r["superseded"] or 0,
                 "avg_wall_s": round(r["avg_wall_ms"] / 1000.0, 1) if r["avg_wall_ms"] else None,
                 "cost_usd": round(r["cost_usd"], 2)}
                for r in by_project
            ],
            "timeseries": [
                {"t": r["t"], "regens": r["regens"] or 0,
                 "avg_wall_s": round(r["avg_wall_ms"] / 1000.0, 1) if r["avg_wall_ms"] else None,
                 "cost_usd": round(r["cost_usd"], 2)}
                for r in series
            ],
            "kinds": [{"kind": r["kind"], "n": r["n"]} for r in kinds],
            "attempts": [{"attempts": k, "n": attempts[k]} for k in sorted(attempts)],
        }
