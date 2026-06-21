"""
Single SQLite store for the dashboard server's runtime data (runtime/dashboard.db).

Two tables, one file:
  - recents:       the most-recently-opened (project, session) queue (server-global).
  - regen_metrics: one row per successful regeneration (tokens, cost, latency),
                   the historical tally surfaced on the dashboard and landing.

This replaces the earlier separate server-global state.json + metrics.db files: it keeps the
runtime dir tidy and the data queryable. Per-CHAT state (acks, regen errors)
deliberately does NOT live here -- it stays co-located next to each chat's
dashboard.html (see chat_state.ChatState) so it travels with the chat.

Best-effort and thread-safe (one process, many daemon threads): a failed write
must never affect whether a dashboard regenerates, so callers tolerate errors.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from logging_config import get_logger

_log = get_logger("store")

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


class DashboardStore:
    """Server-global recents queue + historical regen metrics in one SQLite db."""

    def __init__(self, db_path: Path, *, max_recents: int = 5):
        self._db_path = Path(db_path)
        self._max_recents = max_recents
        self._lock = threading.Lock()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(_SCHEMA)
                conn.commit()
            finally:
                conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    # ─── Recents (server-global, most-recently-opened first, capped) ──

    def touch_open(self, project_hash: str, session_uuid: str) -> None:
        # Sub-second resolution so rapid back-to-back opens order deterministically
        # (the API still exposes openedAt as epoch seconds; see recents()).
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
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
                conn.commit()
            except sqlite3.Error as e:
                _log.warning("store: touch_open failed: %s", e)
            finally:
                conn.close()

    def recents(self) -> "list[dict]":
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT project_hash, session_uuid, opened_at FROM recents "
                    "ORDER BY opened_at DESC LIMIT ?",
                    (self._max_recents,),
                ).fetchall()
            except sqlite3.Error as e:
                _log.warning("store: recents read failed: %s", e)
                rows = []
            finally:
                conn.close()
        # opened_at is stored sub-second for stable ordering; the API exposes it
        # as epoch seconds (the prior contract the frontend expects).
        return [
            {"project": r["project_hash"], "session": r["session_uuid"],
             "openedAt": int(r["opened_at"])}
            for r in rows
        ]

    def forget_open(self, project_hash: str, session_uuid: str) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "DELETE FROM recents WHERE project_hash=? AND session_uuid=?",
                    (project_hash, session_uuid),
                )
                conn.commit()
            except sqlite3.Error as e:
                _log.warning("store: forget_open failed: %s", e)
            finally:
                conn.close()

    # ─── Regen metrics (historical, all sessions) ─────────────────────

    def record(
        self,
        *,
        project_hash: str,
        session_uuid: str,
        model: "str | None" = None,
        status: str = "ok",
        input_tokens: "int | None" = None,
        output_tokens: "int | None" = None,
        cost_usd: "float | None" = None,
        duration_ms: "int | None" = None,
        wall_ms: "int | None" = None,
        ts: "int | None" = None,
    ) -> None:
        ts = int(ts if ts is not None else time.time())
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO regen_metrics"
                    "(ts, project_hash, session_uuid, model, status, input_tokens,"
                    " output_tokens, cost_usd, duration_ms, wall_ms)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (ts, project_hash, session_uuid, model, status,
                     input_tokens, output_tokens, cost_usd, duration_ms, wall_ms),
                )
                conn.commit()
            finally:
                conn.close()

    def session_summary(self, session_uuid: str) -> dict:
        return self._summary("WHERE session_uuid=? AND status='ok'", (session_uuid,))

    def totals(self) -> dict:
        return self._summary("WHERE status='ok'", ())

    def _summary(self, where: str, params: tuple) -> dict:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT COUNT(*) AS regens,"
                    " COALESCE(SUM(input_tokens),0) AS input_tokens,"
                    " COALESCE(SUM(output_tokens),0) AS output_tokens,"
                    " COALESCE(SUM(cost_usd),0.0) AS cost_usd,"
                    " AVG(wall_ms) AS avg_wall_ms,"
                    " MAX(wall_ms) AS max_wall_ms"
                    f" FROM regen_metrics {where}",
                    params,
                ).fetchone()
            except sqlite3.Error as e:
                _log.warning("store: summary read failed: %s", e)
                row = None
            finally:
                conn.close()
        d = dict(row) if row else {}
        if d.get("avg_wall_ms") is not None:
            d["avg_wall_ms"] = round(d["avg_wall_ms"])
        return d
