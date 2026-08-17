"""Live app-wide notices: producers raise codes, recovery clears them."""

from __future__ import annotations

import threading
import time


class NoticeCenter:
    """Thread-safe set of active app-scope notice codes."""

    def __init__(self, probe_interval_s: float = 300.0):
        self._lock = threading.Lock()
        self._active: "dict[str, dict]" = {}
        self._generation = 0
        self._probe_interval_s = probe_interval_s
        self._probe_started_at: "float | None" = None
        self._probing = False

    def raise_(self, code: str, detail: str = "") -> None:
        with self._lock:
            current = self._active.get(code)
            if current is not None and current["detail"] == detail:
                return
            self._active[code] = {"detail": detail, "at": int(time.time())}
            self._generation += 1

    def clear(self, *, code: str = "", prefix: str = "") -> None:
        with self._lock:
            gone = [c for c in self._active
                    if (code and c == code) or (prefix and c.startswith(prefix))]
            for c in gone:
                del self._active[c]
            if gone:
                self._generation += 1

    def has(self, prefix: str) -> bool:
        with self._lock:
            return any(c.startswith(prefix) for c in self._active)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "generation": self._generation,
                "notices": [
                    {"code": code, "detail": entry["detail"], "at": entry["at"]}
                    for code, entry in self._active.items()
                ],
            }

    def begin_probe(self) -> bool:
        """Claim the one probe slot; False while a probe is running or recent."""
        with self._lock:
            now = time.monotonic()
            if self._probing:
                return False
            if (self._probe_started_at is not None
                    and now - self._probe_started_at < self._probe_interval_s):
                return False
            self._probing = True
            self._probe_started_at = now
            return True

    def end_probe(self) -> None:
        with self._lock:
            self._probing = False
