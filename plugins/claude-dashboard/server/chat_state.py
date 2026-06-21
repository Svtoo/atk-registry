"""
Per-chat state — generic ackable items keyed by (project_hash, session_uuid).

Each chat carries a sibling state.json next to its dashboard.html. Two
section kinds live there today; the file is shaped to absorb more:

  {
    "version": 1,
    "acks":         { "<row-id>": { "ackedAt": <epoch> } },
    "regenErrors":  [ { "id", "at", "kind", "message", "ackedAt" }, ... ]
  }

ACKS — heads-up watch-deck rows the user dismissed. Authored by the
dashboard's regen subagent inside the fragment as <tr data-row-id="…">.
The server only remembers which row-ids are dismissed.

REGEN ERRORS — system-emitted records of failed regen attempts. Each
gets a unique id and its own ackedAt so the user can dismiss them one
at a time, exactly like the heads-up acks. Persistence is the whole
point: a transient toast that vanishes in 8s is the wrong shape for a
"your dashboard didn't update" signal — the user needs to see it next
time they look, and acknowledge it on their own schedule.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid as uuid_module
from pathlib import Path

from logging_config import get_logger

_log = get_logger("chat-state")

CURRENT_VERSION = 1
MAX_ERRORS_PER_CHAT = 50
# Per-error message ceiling. Two 2 KB stream dumps + headers fit comfortably;
# anything wilder than that is almost certainly noise (binary blob, runaway
# loop) and not worth bloating state.json over. With MAX_ERRORS_PER_CHAT
# this caps state.json at ~200 KB even in worst case.
MAX_ERROR_MESSAGE_CHARS = 4096
CURRENT_FILENAME = "state.json"

# Row IDs are kebab-ish slugs the agent assigns to heads-up rows; keep
# the charset tight so path segments can't introduce ../ traversal.
_ACK_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_\-]{0,127}$")
# Error IDs are server-generated `err-<epoch>-<8hex>` — fixed shape.
_ERR_ID_RE = re.compile(r"^err-\d{10,}-[0-9a-f]{8}$")


class ChatState:
    """Owns the per-chat state.json files under PROJECTS_ROOT/<h>/<s>/.

    All public methods take (project_hash, session_uuid) and validate
    that the resolved path lives inside PROJECTS_ROOT — no traversal
    out via crafted hashes. A single lock guards reads/writes; the
    files are small enough that per-file locking would be premature.
    """

    def __init__(self, projects_root: Path):
        self._root = projects_root.resolve()
        self._lock = threading.Lock()

    # ─── Path resolution ───────────────────────────────────────────

    def _session_dir(self, project_hash: str, session_uuid: str) -> "Path | None":
        candidate = (self._root / project_hash / session_uuid).resolve()
        try:
            candidate.relative_to(self._root)
        except ValueError:
            return None
        if not candidate.is_dir():
            return None
        return candidate

    def state_path(self, project_hash: str, session_uuid: str) -> "Path | None":
        """Path to the per-chat state.json (or None if the session dir
        is missing / escapes PROJECTS_ROOT)."""
        d = self._session_dir(project_hash, session_uuid)
        return None if d is None else d / CURRENT_FILENAME

    # ─── Read / write primitives ───────────────────────────────────

    @staticmethod
    def _empty_state() -> dict:
        return {"version": CURRENT_VERSION, "acks": {}, "regenErrors": []}

    def _read_locked(self, path: Path) -> dict:
        """Load the per-chat state file, or an empty state if it's missing or
        unreadable."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._empty_state()
        if not isinstance(data, dict):
            return self._empty_state()
        # Forward-compatible normalisation: only the keys we recognise
        # are mapped through; future versions extend by adding keys.
        acks = data.get("acks")
        if not isinstance(acks, dict):
            acks = {}
        errors = data.get("regenErrors")
        if not isinstance(errors, list):
            errors = []
        return {
            "version": CURRENT_VERSION,
            "acks": acks,
            "regenErrors": errors,
        }

    def _write_locked(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
            os.replace(tmp, path)
        except OSError as e:
            _log.warning("chat-state: failed to persist %s: %s", path, e)

    # ─── Public read API ───────────────────────────────────────────

    def snapshot(self, project_hash: str, session_uuid: str) -> "dict | None":
        """Return the full {acks, regenErrors} object for one chat, or
        None if the session dir doesn't exist."""
        path = self.state_path(project_hash, session_uuid)
        if path is None:
            return None
        with self._lock:
            return self._read_locked(path)

    # ─── Acks API ──────────────────────────────────────────────────

    @staticmethod
    def is_valid_row_id(row_id: str) -> bool:
        return bool(_ACK_ID_RE.match(row_id))

    def set_ack(self, project_hash: str, session_uuid: str, row_id: str) -> dict:
        """Mark a heads-up row acknowledged. Returns the new entry."""
        path = self.state_path(project_hash, session_uuid)
        if path is None:
            raise FileNotFoundError("session not found")
        entry = {"ackedAt": int(time.time())}
        with self._lock:
            data = self._read_locked(path)
            data["acks"][row_id] = entry
            self._write_locked(path, data)
        return entry

    def clear_ack(self, project_hash: str, session_uuid: str, row_id: str) -> None:
        path = self.state_path(project_hash, session_uuid)
        if path is None:
            raise FileNotFoundError("session not found")
        with self._lock:
            data = self._read_locked(path)
            if data["acks"].pop(row_id, None) is not None:
                self._write_locked(path, data)

    # ─── Errors API ────────────────────────────────────────────────

    @staticmethod
    def is_valid_error_id(error_id: str) -> bool:
        return bool(_ERR_ID_RE.match(error_id))

    @staticmethod
    def _mint_error_id() -> str:
        # epoch + 8-hex random suffix → unique across rapid back-to-back
        # failures without needing a counter.
        return f"err-{int(time.time())}-{uuid_module.uuid4().hex[:8]}"

    def record_error(
        self,
        project_hash: str,
        session_uuid: str,
        *,
        kind: str,
        message: str,
    ) -> "dict | None":
        """Append a new regen error. Returns the entry (or None if the
        session dir doesn't exist — fail open; we don't want a missing
        sidecar to crash the regen runner)."""
        path = self.state_path(project_hash, session_uuid)
        if path is None:
            _log.warning(
                "chat-state: cannot record error for missing session %s/%s",
                project_hash, session_uuid,
            )
            return None
        # Cap message length to bound state.json size — full diagnostic
        # is also in runtime/server.log if more context is needed.
        msg = message or ""
        if len(msg) > MAX_ERROR_MESSAGE_CHARS:
            msg = msg[:MAX_ERROR_MESSAGE_CHARS] + "\n…[truncated, full text in server.log]"
        entry = {
            "id": self._mint_error_id(),
            "at": int(time.time()),
            "kind": kind,
            "message": msg,
            "ackedAt": None,
        }
        with self._lock:
            data = self._read_locked(path)
            data["regenErrors"].append(entry)
            # Bound the history. Trim oldest first; acked + unacked both
            # count, so a healthy chat self-prunes once it crosses the cap.
            if len(data["regenErrors"]) > MAX_ERRORS_PER_CHAT:
                data["regenErrors"] = data["regenErrors"][-MAX_ERRORS_PER_CHAT:]
            self._write_locked(path, data)
        return entry

    def ack_error(self, project_hash: str, session_uuid: str, error_id: str) -> "dict | None":
        path = self.state_path(project_hash, session_uuid)
        if path is None:
            raise FileNotFoundError("session not found")
        with self._lock:
            data = self._read_locked(path)
            for e in data["regenErrors"]:
                if e["id"] == error_id:
                    e["ackedAt"] = int(time.time())
                    self._write_locked(path, data)
                    return e
        return None

    def unack_error(self, project_hash: str, session_uuid: str, error_id: str) -> None:
        path = self.state_path(project_hash, session_uuid)
        if path is None:
            raise FileNotFoundError("session not found")
        with self._lock:
            data = self._read_locked(path)
            changed = False
            for e in data["regenErrors"]:
                if e["id"] == error_id and e["ackedAt"] is not None:
                    e["ackedAt"] = None
                    changed = True
                    break
            if changed:
                self._write_locked(path, data)
