"""Per-chat state, one state.json beside each chat's dashboard.html:

  {
    "version": 1,
    "acks":         { "<row-id>": { "ackedAt": <epoch> } },
    "regenErrors":  [ { "id", "at", "kind", "message", "ackedAt" }, ... ],
    "model":        { ...DashboardModel as JSON... } | null
  }
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
# With MAX_ERRORS_PER_CHAT this caps state.json at ~200 KB worst case.
MAX_ERROR_MESSAGE_CHARS = 4096
CURRENT_FILENAME = "state.json"

# The tight charsets keep these ids safe as URL path segments.
_ACK_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_\-]{0,127}$")
# Error ids are server-minted `err-<epoch>-<8hex>`.
_ERR_ID_RE = re.compile(r"^err-\d{10,}-[0-9a-f]{8}$")


class ChatState:
    """Owns the per-chat state.json files under PROJECTS_ROOT/<h>/<s>/.
    Every public method validates that the resolved path stays inside
    PROJECTS_ROOT; a single lock guards reads and writes."""

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
    def empty_state() -> dict:
        """The default state shape."""
        return {"version": CURRENT_VERSION, "acks": {}, "regenErrors": [], "model": None}

    def _read_locked(self, path: Path) -> dict:
        """Load the per-chat state file, or an empty state if it's missing or
        unreadable."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self.empty_state()
        if not isinstance(data, dict):
            return self.empty_state()
        acks = data.get("acks")
        if not isinstance(acks, dict):
            acks = {}
        errors = data.get("regenErrors")
        if not isinstance(errors, list):
            errors = []
        model = data.get("model")
        if not isinstance(model, dict):
            model = None
        return {
            "version": CURRENT_VERSION,
            "acks": acks,
            "regenErrors": errors,
            "model": model,
        }

    def _write_locked(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
            os.replace(tmp, path)
        except OSError as e:
            _log.warning("chat-state: failed to persist %s: %s", path, e)

    def _mutate(self, project_hash: str, session_uuid: str, fn):
        """Load the chat's state, apply `fn(data)`, persist when `fn` returns a
        truthy result, and return that result. Raises FileNotFoundError when
        the session dir is missing."""
        path = self.state_path(project_hash, session_uuid)
        if path is None:
            raise FileNotFoundError("session not found")
        with self._lock:
            data = self._read_locked(path)
            result = fn(data)
            if result:
                self._write_locked(path, data)
        return result

    # ─── Public read API ───────────────────────────────────────────

    def snapshot(self, project_hash: str, session_uuid: str) -> "dict | None":
        """The full per-chat state object, or None if the session dir is
        missing."""
        path = self.state_path(project_hash, session_uuid)
        if path is None:
            return None
        with self._lock:
            return self._read_locked(path)

    # ─── Dashboard model API ───────────────────────────────────────

    def get_model(self, project_hash: str, session_uuid: str) -> "dict | None":
        """The server-owned DashboardModel (JSON dict) for one chat, or None if
        there is no session dir / no model persisted yet (a fresh chat)."""
        path = self.state_path(project_hash, session_uuid)
        if path is None:
            return None
        with self._lock:
            return self._read_locked(path).get("model")

    def set_model(self, project_hash: str, session_uuid: str, model: dict) -> None:
        """Persist the folded DashboardModel, preserving regenErrors and the
        acks whose heads-up rows still exist."""
        live_rows = {h.get("id") for h in (model.get("headsup") or [])}

        def apply(data: dict) -> bool:
            data["model"] = model
            data["acks"] = {k: v for k, v in data["acks"].items() if k in live_rows}
            return True

        self._mutate(project_hash, session_uuid, apply)

    # ─── Acks API ──────────────────────────────────────────────────

    @staticmethod
    def is_valid_row_id(row_id: str) -> bool:
        return bool(_ACK_ID_RE.match(row_id))

    def set_ack(self, project_hash: str, session_uuid: str, row_id: str) -> dict:
        """Mark a heads-up row acknowledged. Returns the new entry."""
        entry = {"ackedAt": int(time.time())}

        def apply(data: dict) -> dict:
            data["acks"][row_id] = entry
            return entry

        return self._mutate(project_hash, session_uuid, apply)

    def clear_ack(self, project_hash: str, session_uuid: str, row_id: str) -> None:
        self._mutate(project_hash, session_uuid,
                     lambda data: data["acks"].pop(row_id, None) is not None)

    # ─── Errors API ────────────────────────────────────────────────

    @staticmethod
    def is_valid_error_id(error_id: str) -> bool:
        return bool(_ERR_ID_RE.match(error_id))

    @staticmethod
    def _mint_error_id() -> str:
        return f"err-{int(time.time())}-{uuid_module.uuid4().hex[:8]}"

    def record_error(
        self,
        project_hash: str,
        session_uuid: str,
        *,
        kind: str,
        message: str,
    ) -> "dict | None":
        """Append a new regen error. Returns the entry, or None if the session
        dir does not exist (a missing sidecar must not crash the regen runner)."""
        msg = message or ""
        if len(msg) > MAX_ERROR_MESSAGE_CHARS:
            msg = msg[:MAX_ERROR_MESSAGE_CHARS] + "\n…[truncated, full text in server.log]"
        entry = {
            "id": self._mint_error_id(),
            "at": int(time.time()),
            "kind": kind,
            "message": msg,
            "ackedAt": None,
            "resolvedAt": None,
        }

        def apply(data: dict) -> dict:
            data["regenErrors"].append(entry)
            if len(data["regenErrors"]) > MAX_ERRORS_PER_CHAT:
                data["regenErrors"] = data["regenErrors"][-MAX_ERRORS_PER_CHAT:]
            return entry

        try:
            return self._mutate(project_hash, session_uuid, apply)
        except FileNotFoundError:
            _log.warning(
                "chat-state: cannot record error for missing session %s/%s",
                project_hash, session_uuid,
            )
            return None

    def resolve_errors(self, project_hash: str, session_uuid: str) -> None:
        """Stamp resolvedAt on every open error; a later successful regen has
        made them moot. Acked and already-resolved entries stay untouched."""
        def apply(data: dict) -> bool:
            now = int(time.time())
            changed = False
            for e in data["regenErrors"]:
                if e.get("ackedAt") is None and e.get("resolvedAt") is None:
                    e["resolvedAt"] = now
                    changed = True
            return changed

        try:
            self._mutate(project_hash, session_uuid, apply)
        except FileNotFoundError:
            pass

    def ack_error(self, project_hash: str, session_uuid: str, error_id: str) -> "dict | None":
        def apply(data: dict) -> "dict | None":
            for e in data["regenErrors"]:
                if e["id"] == error_id:
                    e["ackedAt"] = int(time.time())
                    return e
            return None

        return self._mutate(project_hash, session_uuid, apply)

    def unack_error(self, project_hash: str, session_uuid: str, error_id: str) -> None:
        def apply(data: dict) -> bool:
            for e in data["regenErrors"]:
                if e["id"] == error_id and e["ackedAt"] is not None:
                    e["ackedAt"] = None
                    return True
            return False

        self._mutate(project_hash, session_uuid, apply)
