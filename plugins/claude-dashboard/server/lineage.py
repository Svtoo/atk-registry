"""Which chat a session continues from.

Claude Code starts a new session id when a chat is resumed, compacted, or
forked, and the new transcript replays the old one's events verbatim. Shared
event uuids are therefore the whole signal: no timing, no app-private files,
and no attempt to name which of the three happened — "continued from" holds
for all of them.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

# Below this many shared events a match is coincidence, not a replayed history.
MIN_SHARED = 5
# Reading a transcript's uuids is the expensive part; a replay always starts
# at the beginning, so a bounded head is enough to identify one.
MAX_UUIDS = 4000


def read_uuids(jsonl_path: Path) -> "list[str]":
    """Event uuids from the head of a transcript, in file order."""
    out: "list[str]" = []
    try:
        with jsonl_path.open("r", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                u = d.get("uuid")
                if isinstance(u, str) and u:
                    out.append(u)
                    if len(out) >= MAX_UUIDS:
                        break
    except OSError:
        pass
    return out


class LineageIndex:
    """Per-project uuid sets, rebuilt when any transcript in the dir changes."""

    def __init__(self):
        self._dirs: "dict[str, dict]" = {}
        self._lock = threading.Lock()
        self.scan_count = 0

    @staticmethod
    def _stamp(proj_dir: Path) -> tuple:
        out = []
        try:
            for p in sorted(proj_dir.glob("*.jsonl")):
                try:
                    st = p.stat()
                except OSError:
                    continue
                out.append((p.name, st.st_mtime, st.st_size))
        except OSError:
            pass
        return tuple(out)

    @staticmethod
    def _born(p: Path) -> float:
        try:
            st = p.stat()
        except OSError:
            return 0.0
        return getattr(st, "st_birthtime", st.st_ctime)

    def _entries(self, proj_dir: Path) -> dict:
        key = str(proj_dir)
        stamp = self._stamp(proj_dir)
        with self._lock:
            cached = self._dirs.get(key)
            if cached is not None and cached["stamp"] == stamp:
                return cached["sessions"]
        sessions = {p.stem: {"uuids": read_uuids(p), "born": self._born(p)}
                    for p in sorted(proj_dir.glob("*.jsonl"))}
        with self._lock:
            self._dirs[key] = {"stamp": stamp, "sessions": sessions}
            self.scan_count += 1
        return sessions

    def parent_of(self, jsonl_path: Path) -> "str | None":
        """The session this transcript continues from, or None.

        Shared events decide whether two transcripts are the same
        conversation; file creation order only decides which of the two came
        first, since a continuation cannot predate what it replays."""
        sessions = self._entries(jsonl_path.parent)
        me = sessions.get(jsonl_path.stem)
        if not me or not me["uuids"]:
            return None
        mine = set(me["uuids"])
        best, best_n = None, 0
        for session, entry in sessions.items():
            if session == jsonl_path.stem or not entry["uuids"]:
                continue
            if entry["born"] >= me["born"]:
                continue
            shared = len(mine.intersection(entry["uuids"]))
            if shared >= MIN_SHARED and shared > best_n:
                best, best_n = session, shared
        return best


_INDEX = LineageIndex()


def find_parent(jsonl_path: Path) -> "str | None":
    return _INDEX.parent_of(jsonl_path)
