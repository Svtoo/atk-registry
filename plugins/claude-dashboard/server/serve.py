#!/usr/bin/env python3
"""
Multi-project dashboard server for Claude Code.

Serves the user's Claude Code chat-history directory (default ~/.claude/projects/)
via HTTP on a fixed port. Endpoints:

  GET /                                      → projects-landing template
  GET /<project-hash>/                       → project-index template
  GET /<project-hash>/<session-uuid>/dashboard.html
                                             → fragment wrapped with _layout.html,
                                               or legacy full document served as-is
  GET /api/projects.json                     → JSON: all projects with metadata
  GET /api/recents.json                      → JSON: recents queue (opened order)
  GET /api/latest.json                       → JSON: freshest dashboards, all projects
  GET /api/sessions/<project-hash>.json      → JSON: sessions for one project
  GET /api/dashboard/<hash>/<uuid>.json      → per-chat sidecar (acks etc.)
  POST/DELETE /api/dashboard/<hash>/<uuid>/acknowledge/<row-id>
                                             → toggle a heads-up acknowledgement
  GET /assets/<path>                         → plugin static assets (CSS, JS, images)

Templates use `{{placeholder}}` substitution. The shared `<head>` block lives
in templates/_head.html and is injected into any template via `{{shared_head}}`.
Per-chat dashboards rendered as fragments are wrapped by templates/_layout.html.

Environment variables (atk-level config; see plugin.yaml):
  PORT                     TCP port to bind (default 7878, loopback only)
  CLAUDE_PROJECTS_DIR      Override projects root (default ~/.claude/projects)
  CCD_MODEL                Model for `claude -p` regen (default sonnet)
  CCD_N_TURNS              Recent turns fed to the prompt (default 6)
  CCD_MAX_TRANSCRIPT_WORDS Word budget for the recent transcript (default 20000)
  CCD_REGEN_TIMEOUT        Seconds before a wedged regen is killed (default 180)
"""

import http.server
import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

# Local modules: serve.py is launched via `python3 server/serve.py`, so the
# server dir is the CWD's interpreter path. Importing regen/logging_config
# by bare name works because they live in the same dir.
from chat_state import ChatState
from logging_config import configure_logging, get_logger
from regen import (
    AMBIENT_AUTH_VARS,
    DEFAULT_MAX_TRANSCRIPT_WORDS,
    DEFAULT_MODEL,
    DEFAULT_N_TURNS,
    DEFAULT_REGEN_TIMEOUT,
    Registry,
    probe_auth,
)
from store import DashboardStore

PORT = int(os.environ.get("PORT", 7878))
PROJECTS_ROOT = Path(
    os.environ.get("CLAUDE_PROJECTS_DIR")
    or (Path.home() / ".claude" / "projects")
)
# Plugin layout: <plugin>/server/serve.py — parent of parent is plugin root.
PLUGIN_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = PLUGIN_DIR / "templates"
ASSETS_DIR = PLUGIN_DIR / "assets"
RUNTIME_DIR = PLUGIN_DIR / "runtime"

_log = get_logger("serve")


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    """Read an optional integer env var. Missing -> default; malformed -> log a
    warning and use the default (a long-running daemon should not refuse to
    start over a typo in optional config)."""
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        val = int(raw)
    except ValueError:
        _log.warning("ignoring %s=%r (not an integer); using %d", name, raw, default)
        return default
    if val < minimum:
        _log.warning("ignoring %s=%d (below minimum %d); using %d", name, val, minimum, default)
        return default
    return val


def _env_float(name: str, default: float, *, minimum: float = 1.0) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        val = float(raw)
    except ValueError:
        _log.warning("ignoring %s=%r (not a number); using %s", name, raw, default)
        return default
    if val < minimum:
        _log.warning("ignoring %s=%s (below minimum %s); using %s", name, val, minimum, default)
        return default
    return val


# Regen config (atk-level env_vars, see plugin.yaml) is resolved in main() AFTER
# logging is configured, so a malformed-value warning is captured in the log
# rather than discarded (at import there are no handlers, and under nohup stderr
# goes to /dev/null).

# Shared in-memory state — initialised in main() so import-time has no
# side effects (matters for smoke-test imports). STORE owns the recents queue
# and the historical regen metrics (one SQLite db); the Registry tracks
# in-flight regen jobs (transient, not persisted); CHAT_STATE owns the per-chat
# state.json sidecars (acks, regen errors), co-located with each chat.
REGISTRY: "Registry | None" = None
STORE: "DashboardStore | None" = None
CHAT_STATE: "ChatState | None" = None

# Auth health of the regen subagent, filled by a startup probe (see main()).
# Surfaced at /api/health.json and as a banner so a broken auth/billing state
# is obvious immediately instead of being discovered via missing dashboards.
AUTH_HEALTH: dict = {"regenAuth": None, "detail": "probe not run yet", "checkedAt": None}

_meta_cache: "dict[str, dict]" = {}
_meta_cache_lock = threading.Lock()


def parse_session_meta(jsonl_path: Path, max_lines: int = 100) -> dict:
    """Pull ai-title and the first user message from a session JSONL."""
    ai_title = ""
    first_user = ""
    try:
        with jsonl_path.open("r", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i >= max_lines:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get("type") == "ai-title" and not ai_title:
                    ai_title = (d.get("aiTitle") or "").strip()
                if d.get("type") == "user" and not first_user:
                    m = d.get("message", {})
                    c = m.get("content", "")
                    if isinstance(c, str):
                        first_user = c[:200].replace("\n", " ").strip()
                    elif isinstance(c, list) and c:
                        for item in c:
                            if isinstance(item, dict) and "text" in item:
                                first_user = item["text"][:200].replace("\n", " ").strip()
                                break
                if ai_title and first_user:
                    break
    except Exception:
        pass
    return {"aiTitle": ai_title, "firstUser": first_user}


def get_meta_cached(jsonl_path: Path) -> dict:
    key = str(jsonl_path)
    try:
        mtime = jsonl_path.stat().st_mtime
    except OSError:
        # File gone since we last cached it — evict so the cache doesn't
        # grow monotonically as chats are deleted.
        with _meta_cache_lock:
            _meta_cache.pop(key, None)
        return {}
    with _meta_cache_lock:
        entry = _meta_cache.get(key)
        if entry and entry["mtime"] == mtime:
            return entry["data"]
    data = parse_session_meta(jsonl_path)
    with _meta_cache_lock:
        _meta_cache[key] = {"mtime": mtime, "data": data}
    return data


_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.DOTALL | re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


# ─── Last-completed-turn detection ─────────────────────────────────────
# The file mtime advances every time Claude Code writes a line — including
# when the user types a new message or a tool_result lands. The status
# chip wants a tighter signal: "when did the agent last FINISH a turn?"
# That's the most recent assistant event whose content has no pending
# tool_use blocks. We scan backwards from EOF so big sessions don't pay
# a full re-read on every API call.

_last_turn_cache: "dict[str, dict]" = {}
_last_turn_cache_lock = threading.Lock()


def _parse_jsonl_timestamp(ts) -> "int | None":
    """Convert ISO-8601 (with trailing Z) to epoch seconds. Returns None
    on anything unparseable so callers can fall back to file mtime."""
    if not isinstance(ts, str):
        return None
    try:
        from datetime import datetime
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return int(datetime.fromisoformat(ts).timestamp())
    except (ValueError, TypeError):
        return None


def _is_user_typed_message(ev: dict) -> bool:
    """True iff this user event represents a NEW message the user typed,
    not just a tool_result piggy-backed on a user-role line. Used as the
    "turn boundary" signal — a real user message after an assistant text
    confirms the assistant text was the closing word of that turn."""
    if ev.get("type") != "user":
        return False
    content = ev.get("message", {}).get("content")
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        return any(
            isinstance(b, dict) and b.get("type") == "text"
            for b in content
        )
    return False


def _is_assistant_turn_end(ev: dict, next_ev: "dict | None") -> bool:
    """True iff `ev` is an assistant message that closed a turn — i.e.
    text-only content AND either nothing follows in the file OR the next
    event is a user-typed message (turn boundary).

    Without the lookahead, a mid-turn "Let me check…" text block before
    a tool_use would be misread as a turn-end and corrupt the "behind"
    calc whenever the agent thinks-then-tools.
    """
    if ev.get("type") != "assistant":
        return False
    content = ev.get("message", {}).get("content")
    if isinstance(content, list):
        has_tool_use = any(
            isinstance(b, dict) and b.get("type") == "tool_use"
            for b in content
        )
        if has_tool_use:
            return False
        has_text = any(
            isinstance(b, dict) and b.get("type") == "text"
            for b in content
        )
        if not has_text:
            return False
    elif not isinstance(content, str):
        return False
    # Lookahead: either we're at EOF (nothing newer) or a user-typed
    # message follows — both indicate this assistant text closed a turn.
    return next_ev is None or _is_user_typed_message(next_ev)


def _scan_last_turn_end(jsonl_path: Path) -> "int | None":
    """Walk the JSONL backwards in 64 KB chunks; return the epoch of the
    most recent assistant event that closed a turn. "Closed" = text-only
    content followed by either a user-typed message or EOF. The lookahead
    means we don't mistake mid-turn "Let me check…" text for a turn-end."""
    try:
        size = jsonl_path.stat().st_size
    except OSError:
        return None
    if size == 0:
        return None

    chunk_size = 65536
    leftover = b""
    pos = size
    next_ev: "dict | None" = None  # chronologically newer than the one we just looked at

    with jsonl_path.open("rb") as fh:
        while pos > 0:
            read_size = min(chunk_size, pos)
            pos -= read_size
            fh.seek(pos)
            data = fh.read(read_size) + leftover
            lines = data.split(b"\n")
            # If pos > 0 there's more file before this chunk; the first
            # element is a fragment of a line that started earlier — save
            # it as `leftover` for the next pass.
            if pos > 0:
                leftover = lines[0]
                relevant = lines[1:]
            else:
                leftover = b""
                relevant = lines
            for raw in reversed(relevant):
                if not raw.strip():
                    continue
                try:
                    ev = json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if _is_assistant_turn_end(ev, next_ev):
                    return _parse_jsonl_timestamp(ev.get("timestamp"))
                next_ev = ev
    return None


def get_last_turn_end_cached(jsonl_path: Path) -> "int | None":
    """Memoise _scan_last_turn_end keyed on (path, mtime). Cache turns
    over automatically when the JSONL gets new writes."""
    key = str(jsonl_path)
    try:
        mtime = jsonl_path.stat().st_mtime
    except OSError:
        with _last_turn_cache_lock:
            _last_turn_cache.pop(key, None)
        return None
    with _last_turn_cache_lock:
        entry = _last_turn_cache.get(key)
        if entry and entry["mtime"] == mtime:
            return entry["value"]
    value = _scan_last_turn_end(jsonl_path)
    with _last_turn_cache_lock:
        _last_turn_cache[key] = {"mtime": mtime, "value": value}
    return value


def extract_title(content: str, fallback: str) -> str:
    """Pull the first <h1>'s text out of a dashboard fragment for use as
    the browser <title>. Returns `fallback` if no h1 is found."""
    m = _H1_RE.search(content)
    if not m:
        return fallback
    return _HTML_TAG_RE.sub("", m.group(1)).strip() or fallback


def read_template(name: str) -> str:
    """Read a template file. Returns empty string if missing."""
    p = TEMPLATES_DIR / name
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def apply_substitutions(template: str, substitutions: dict) -> str:
    """Replace `{{key}}` placeholders. `{{shared_head}}` always pulls
    templates/_head.html so every page renders the same head bits."""
    out = template.replace("{{shared_head}}", read_template("_head.html"))
    for k, v in substitutions.items():
        out = out.replace(f"{{{{{k}}}}}", str(v))
    return out


# Git worktree dirs created by Claude Code show up alongside the parent
# project as their own entries — e.g. parent
#   -Users-…-frontline-frontlineiq
# spawns
#   -Users-…-frontline-frontlineiq--claude-worktrees-nice-brahmagupta-9a7f55
# We collapse those under the parent in list_projects() so the landing
# doesn't get polluted with hash-only labels.
WT_MARKER = "--claude-worktrees-"


def parse_project_hash(project_hash: str) -> dict:
    """Extract worktree-vs-parent info from a project-hash dir name."""
    if WT_MARKER in project_hash:
        parent_hash, wt_part = project_hash.split(WT_MARKER, 1)
        parent_parts = [p for p in parent_hash.split("-") if p]
        parent_label = parent_parts[-1] if parent_parts else parent_hash
        wt_segments = [s for s in wt_part.split("-") if s]
        # wt_part is "<adjective>-<noun>-<6char-hash>"; the hash is the last segment.
        wt_name = "-".join(wt_segments[:-1]) if len(wt_segments) >= 2 else wt_part
        return {
            "isWorktree": True,
            "parentHash": parent_hash,
            "parentLabel": parent_label,
            "worktreeName": wt_name,
        }
    return {
        "isWorktree": False,
        "parentHash": None,
        "parentLabel": None,
        "worktreeName": None,
    }


def project_label(project_hash: str) -> str:
    """Derive a human-readable name from a project-hash dir name."""
    info = parse_project_hash(project_hash)
    if info["isWorktree"]:
        return f"{info['parentLabel']} · wt:{info['worktreeName']}"
    parts = [p for p in project_hash.split("-") if p]
    return parts[-1] if parts else project_hash


def _scan_project(proj_dir: Path) -> "dict | None":
    """Build a raw project entry for one dir, or None if it has no chats."""
    jsonl_files = list(proj_dir.glob("*.jsonl"))
    if not jsonl_files:
        return None
    latest = max(f.stat().st_mtime for f in jsonl_files)
    with_dashboards = sum(
        1 for f in jsonl_files
        if (proj_dir / f.stem / "dashboard.html").is_file()
    )
    info = parse_project_hash(proj_dir.name)
    return {
        "hash": proj_dir.name,
        "label": project_label(proj_dir.name),
        "chatCount": len(jsonl_files),
        "withDashboards": with_dashboards,
        "lastActivity": int(latest),
        "lastActivityIso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(latest)),
        "isWorktree": info["isWorktree"],
        "parentHash": info["parentHash"],
        "worktreeName": info["worktreeName"],
    }


def list_projects() -> list:
    """List projects with worktrees collapsed under their parent."""
    if not PROJECTS_ROOT.is_dir():
        return []
    raw = []
    for proj_dir in sorted(PROJECTS_ROOT.iterdir()):
        if not proj_dir.is_dir():
            continue
        entry = _scan_project(proj_dir)
        if entry is not None:
            raw.append(entry)

    parents: "dict[str, dict]" = {}
    final = []
    # Pass 1: real projects.
    for p in raw:
        if not p["isWorktree"]:
            p["worktrees"] = []
            parents[p["hash"]] = p
            final.append(p)
    # Pass 2: worktrees fold into their parent (or become orphan top-level entries
    # if the parent dir was deleted).
    for p in raw:
        if not p["isWorktree"]:
            continue
        parent = parents.get(p["parentHash"])
        if parent is None:
            p["worktrees"] = []
            final.append(p)
            continue
        parent["worktrees"].append({
            "hash": p["hash"],
            "worktreeName": p["worktreeName"],
            "chatCount": p["chatCount"],
            "withDashboards": p["withDashboards"],
            "lastActivity": p["lastActivity"],
            "lastActivityIso": p["lastActivityIso"],
        })
        # Roll the worktree's chat/dashboard counts and activity up so the parent
        # card surfaces totals — otherwise a heavily-worked worktree looks dead.
        parent["chatCount"] += p["chatCount"]
        parent["withDashboards"] += p["withDashboards"]
        if p["lastActivity"] > parent["lastActivity"]:
            parent["lastActivity"] = p["lastActivity"]
            parent["lastActivityIso"] = p["lastActivityIso"]

    for p in final:
        p["worktrees"].sort(key=lambda w: w["lastActivity"], reverse=True)
    final.sort(key=lambda p: p["lastActivity"], reverse=True)
    return final


def _session_row(
    source_dir: Path,
    jsonl: Path,
    worktree_name: "str | None",
) -> "dict | None":
    """Build the canonical row shape for one session JSONL. Shared by
    /api/sessions (which iterates many) and /api/recents (which iterates
    a tiny pinned list). Returns None if the JSONL is unreadable."""
    uuid = jsonl.stem
    try:
        st = jsonl.stat()
    except OSError:
        return None
    meta = get_meta_cached(jsonl)
    dash_path = source_dir / uuid / "dashboard.html"
    has_dashboard = dash_path.is_file()
    dash_mtime = None
    if has_dashboard:
        try:
            dash_mtime = int(dash_path.stat().st_mtime)
        except OSError:
            pass
    # Execution state from the registry — only present when there's an
    # active or recently-failed regen job for this session. The client
    # treats "no regen block + dashboard exists + mtime ≥ jsonl mtime"
    # as "current" and renders no chip.
    regen_state = REGISTRY.state_for(uuid) if REGISTRY is not None else None
    # Persisted regen errors (state.json) so the index/strip can flag a session
    # whose generation FAILED even when no dashboard.html exists yet — and even
    # after a restart cleared the transient in-memory registry record. Without
    # this, a failed first-gen is invisible everywhere (classify → no chip,
    # page → placeholder). Cheap: one small JSON read per row.
    regen_errors: list = []
    if CHAT_STATE is not None:
        snap = CHAT_STATE.snapshot(source_dir.name, uuid)
        if snap is not None:
            regen_errors = snap.get("regenErrors", [])
    return {
        "uuid": uuid,
        "shortUuid": uuid[:8],
        "mtime": int(st.st_mtime),
        "mtimeIso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(st.st_mtime)),
        "size": st.st_size,
        "aiTitle": meta.get("aiTitle", ""),
        "firstUser": meta.get("firstUser", ""),
        "hasDashboard": has_dashboard,
        "dashboardMtime": dash_mtime,
        # `mtime` alone is a noisy "behind" signal (advances on user-typed
        # messages and tool_results too). Clients should compute behind
        # against lastTurnEndedAt instead, which is the timestamp of the
        # most recent COMPLETED assistant turn (the only thing the regen
        # subagent can actually react to). None means "no completed turn
        # yet" — clients render no "behind" chip in that case.
        "lastTurnEndedAt": get_last_turn_end_cached(jsonl),
        "regen": regen_state,
        "regenErrors": regen_errors,
        "sourceHash": source_dir.name,
        "worktreeName": worktree_name,
    }


def _scan_sessions(source_dir: Path, worktree_name: "str | None", rows: list) -> None:
    """Append session rows from one project dir into `rows`. Worktree-sourced
    rows carry `worktreeName` so the project-index can tag them inline."""
    for jsonl in sorted(source_dir.glob("*.jsonl")):
        row = _session_row(source_dir, jsonl, worktree_name)
        if row is not None:
            rows.append(row)


def list_recents() -> list:
    """Snapshot the recents queue and enrich each entry with the same row
    shape /api/sessions emits. Drops entries whose underlying JSONL is
    gone (and forgets them from the queue so the file self-heals)."""
    if STORE is None:
        return []
    out = []
    for entry in STORE.recents():
        proj = entry["project"]
        sess = entry["session"]
        source_dir = PROJECTS_ROOT / proj
        jsonl = source_dir / f"{sess}.jsonl"
        if not jsonl.is_file():
            STORE.forget_open(proj, sess)
            continue
        row = _session_row(source_dir, jsonl, None)
        if row is None:
            continue
        row["openedAt"] = entry["openedAt"]
        row["projectLabel"] = project_label(proj)
        out.append(row)
    return out


def list_latest(limit: int = 15) -> list:
    """Every session that HAS a dashboard, across all projects, sorted by
    most-recent dashboard update (then last completed turn).

    This is the 'freshness' axis the recents queue lacks. Recents is ordered
    by openedAt (your interaction history); this is ordered by when the
    dashboard last changed — so it surfaces chats you've never opened,
    including background-regenerated child agents in other projects. Only
    sessions with a dashboard.html are included, because clicking a chip
    that has no dashboard would 404."""
    if not PROJECTS_ROOT.is_dir():
        return []
    rows: list = []
    for proj_dir in PROJECTS_ROOT.iterdir():
        if not proj_dir.is_dir():
            continue
        info = parse_project_hash(proj_dir.name)
        wt = info["worktreeName"] if info["isWorktree"] else None
        for jsonl in proj_dir.glob("*.jsonl"):
            row = _session_row(proj_dir, jsonl, wt)
            if row is None or not row["hasDashboard"]:
                continue
            row["projectLabel"] = project_label(proj_dir.name)
            rows.append(row)

    def _freshness(r: dict) -> int:
        return max(r.get("dashboardMtime") or 0, r.get("lastTurnEndedAt") or 0)

    rows.sort(key=_freshness, reverse=True)
    return rows[:limit]


def list_sessions(project_hash: str):
    """Sessions for a project. For a parent project, includes sessions from
    every child worktree dir too — each tagged with worktreeName so the UI
    can show inline which worktree a chat came from. Worktrees themselves
    don't get their own index — see do_GET's redirect."""
    proj_dir = PROJECTS_ROOT / project_hash
    if not proj_dir.is_dir():
        return None
    rows: list = []
    info = parse_project_hash(project_hash)
    _scan_sessions(proj_dir, None, rows)
    # Aggregate worktree sessions under the parent project.
    if not info["isWorktree"]:
        marker = project_hash + WT_MARKER
        for sib in sorted(PROJECTS_ROOT.iterdir()):
            if not sib.is_dir() or not sib.name.startswith(marker):
                continue
            sib_info = parse_project_hash(sib.name)
            _scan_sessions(sib, sib_info["worktreeName"], rows)
    rows.sort(key=lambda r: r["mtime"], reverse=True)
    return rows


# ─── Path-shape validators ─────────────────────────────────────────────
# Per-chat state (acks + regen errors) is owned by ChatState in
# chat_state.py — these regexes still live here because the HTTP routes
# need to validate URL path segments before passing them into ChatState.

# Claude Code session UUIDs are RFC-4122-ish (8-4-4-4-12 hex with hyphens);
# accept the standard shape and reject anything else.
_SESSION_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
# Project-hash dirs are sanitised paths starting with `-`; keep the charset
# tight so we can stitch them straight into PROJECTS_ROOT / <hash> / …
_PROJECT_HASH_RE = re.compile(r"^-[a-zA-Z0-9_\-]{1,255}$")

# Content-Security-Policy applied to every response. This server is
# loopback-only and single-user; the CSP is not about remote attackers but
# about containing the one real risk: a chat transcript that prompt-injects the
# regen model into emitting active HTML. The dashboard is free to render
# anything VISUAL (inline scripts/styles, canvas, SVG, animation, Mermaid from
# the jsdelivr CDN), but every channel that could send your transcripts to an
# external origin is denied: connect/img/font/media are limited to 'self', and
# form submission and framing are off. Injected script can run, but it cannot
# phone home with your data. (cdn.jsdelivr.net is allowed in script-src only so
# the Mermaid diagram library can load.)
_CSP = (
    "default-src 'none'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self' data:; "
    "media-src 'self' data:; "
    "connect-src 'self'; "
    "form-action 'none'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'"
)


class Handler(http.server.SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PROJECTS_ROOT), **kwargs)

    def end_headers(self):
        # No CORS headers. Every legitimate consumer is same-origin (landing,
        # index, and dashboard pages are all served from this origin), so
        # withholding Access-Control-Allow-Origin is exactly what lets the
        # browser's Same-Origin Policy stop a hostile web page from reading your
        # transcripts cross-origin, and the absence of a permissive preflight
        # response blocks cross-origin POSTs to the mutating endpoints.
        self.send_header("Content-Security-Policy", _CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_OPTIONS(self):
        # CORS preflight for the ack endpoints.
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write(
            f"[{time.strftime('%H:%M:%S')}] {self.address_string()} {fmt % args}\n"
        )

    def _require_json(self) -> bool:
        """Mutating requests must declare Content-Type: application/json. This
        is the CSRF guard: a cross-origin page can only send a "simple" request
        (text/plain or form-encoded) without a CORS preflight, so requiring a
        JSON content type forces a preflight that this server — which sends no
        CORS headers — will never satisfy. Same-origin requests are unaffected."""
        ctype = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if ctype != "application/json":
            self.send_error(415, "Content-Type must be application/json")
            return False
        return True

    def do_POST(self):
        if not self._require_json():
            return
        path = urlparse(self.path).path
        parts = [p for p in path.split("/") if p]
        # /api/regen — schedule a fresh dashboard regeneration for one session.
        # Body: {"session": "<uuid>", "project": "<hash>"?}
        # If `project` is omitted the server resolves it by walking the
        # projects root. Returns 202 + state snapshot.
        if len(parts) == 2 and parts[0] == "api" and parts[1] == "regen":
            return self._handle_regen_post()
        # /api/dashboard/<h>/<s>/error/<id>/acknowledge — dismiss regen error
        if (
            len(parts) == 7
            and parts[0] == "api"
            and parts[1] == "dashboard"
            and parts[4] == "error"
            and parts[6] == "acknowledge"
        ):
            return self._handle_error_ack("POST")
        return self._handle_ack_mutation("POST")

    def do_DELETE(self):
        if not self._require_json():
            return
        path = urlparse(self.path).path
        parts = [p for p in path.split("/") if p]
        if (
            len(parts) == 7
            and parts[0] == "api"
            and parts[1] == "dashboard"
            and parts[4] == "error"
            and parts[6] == "acknowledge"
        ):
            return self._handle_error_ack("DELETE")
        return self._handle_ack_mutation("DELETE")

    def _read_json_body(self, max_bytes: int = 4096) -> "dict | None":
        """Parse a small JSON body; returns None on any error (caller
        decides what 4xx to send). Cap at 4 KB — we only ever send tiny
        objects like {"session": "<uuid>"}."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if length <= 0 or length > max_bytes:
            return None
        try:
            raw = self.rfile.read(length).decode("utf-8")
            data = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def _handle_regen_post(self) -> None:
        if REGISTRY is None:
            return self.send_error(503, "registry not initialised")
        body = self._read_json_body()
        if not body:
            return self.send_error(400, "expected JSON body with 'session'")
        session_uuid = body.get("session")
        if not isinstance(session_uuid, str) or not _SESSION_UUID_RE.match(session_uuid):
            return self.send_error(400, "invalid 'session' uuid")
        project_hash = body.get("project")
        if project_hash is not None and not isinstance(project_hash, str):
            return self.send_error(400, "invalid 'project'")
        if not project_hash:
            project_hash = REGISTRY.resolve_project_hash(session_uuid)
            if project_hash is None:
                return self.send_error(404, "session not found under projects root")
        # Path-shape check — same guard as the ack endpoint.
        if not _PROJECT_HASH_RE.match(project_hash):
            return self.send_error(400, "invalid 'project' hash")
        jsonl = PROJECTS_ROOT / project_hash / f"{session_uuid}.jsonl"
        if not jsonl.is_file():
            return self.send_error(404, "session jsonl not found")
        state = REGISTRY.trigger(project_hash, session_uuid)
        self.send_response(202)
        body_bytes = json.dumps({
            "ok": True,
            "project": project_hash,
            "session": session_uuid,
            "regen": state,
        }).encode("utf-8")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        if not getattr(self, "_head_only", False):
            self.wfile.write(body_bytes)

    def do_HEAD(self):
        # Re-use the full do_GET routing for HEAD too so /assets/*,
        # /api/* and the templated pages all respond consistently. The
        # `_head_only` flag suppresses body writes in our custom handlers;
        # the static-file fallback dispatches to parent's do_HEAD which
        # also skips the body. Without this override, HEAD on /assets/*
        # would hit parent's default do_HEAD, look under PROJECTS_ROOT
        # (where assets don't live), and 404.
        self._head_only = True
        try:
            self.do_GET()
        finally:
            self._head_only = False

    def _handle_ack_mutation(self, method: str) -> None:
        """POST/DELETE /api/dashboard/<project>/<session>/acknowledge/<row>
        — toggle a heads-up watch-deck row's acknowledged state."""
        path = urlparse(self.path).path
        parts = [p for p in path.split("/") if p]
        if (
            len(parts) != 6
            or parts[0] != "api"
            or parts[1] != "dashboard"
            or parts[4] != "acknowledge"
        ):
            return self.send_error(404, "unknown endpoint")
        project_hash, session_uuid, row_id = parts[2], parts[3], parts[5]
        if not _PROJECT_HASH_RE.match(project_hash) or not _SESSION_UUID_RE.match(session_uuid):
            return self.send_error(400, "invalid project or session id")
        if not ChatState.is_valid_row_id(row_id):
            return self.send_error(400, "invalid row id")
        if CHAT_STATE is None:
            return self.send_error(503, "chat state not initialised")
        try:
            if method == "POST":
                entry = CHAT_STATE.set_ack(project_hash, session_uuid, row_id)
                state = entry
            else:
                CHAT_STATE.clear_ack(project_hash, session_uuid, row_id)
                state = None
        except FileNotFoundError:
            return self.send_error(404, "session not found")
        return self._send_json({"ok": True, "rowId": row_id, "state": state})

    def _handle_error_ack(self, method: str) -> None:
        """POST/DELETE /api/dashboard/<project>/<session>/error/<id>/acknowledge
        — dismiss (or un-dismiss) a persisted regen error. Mirrors the
        heads-up ack endpoint's lifecycle: the entry stays in state.json
        but its `ackedAt` flips, which is what the UI uses to hide vs
        re-surface the banner card."""
        path = urlparse(self.path).path
        parts = [p for p in path.split("/") if p]
        # /api/dashboard/<project>/<session>/error/<id>/acknowledge
        if (
            len(parts) != 7
            or parts[0] != "api"
            or parts[1] != "dashboard"
            or parts[4] != "error"
            or parts[6] != "acknowledge"
        ):
            return self.send_error(404, "unknown endpoint")
        project_hash, session_uuid, error_id = parts[2], parts[3], parts[5]
        if not _PROJECT_HASH_RE.match(project_hash) or not _SESSION_UUID_RE.match(session_uuid):
            return self.send_error(400, "invalid project or session id")
        if not ChatState.is_valid_error_id(error_id):
            return self.send_error(400, "invalid error id")
        if CHAT_STATE is None:
            return self.send_error(503, "chat state not initialised")
        try:
            if method == "POST":
                entry = CHAT_STATE.ack_error(project_hash, session_uuid, error_id)
                if entry is None:
                    return self.send_error(404, "error not found")
                return self._send_json({"ok": True, "id": error_id, "ackedAt": entry["ackedAt"]})
            else:
                CHAT_STATE.unack_error(project_hash, session_uuid, error_id)
                return self._send_json({"ok": True, "id": error_id, "ackedAt": None})
        except FileNotFoundError:
            return self.send_error(404, "session not found")

    def do_GET(self):
        path = urlparse(self.path).path
        parts = [p for p in path.split("/") if p]

        if not parts:
            return self._serve_template("projects-landing.html")

        if parts[0] == "api":
            if len(parts) == 2 and parts[1] == "projects.json":
                return self._send_json(list_projects())
            if len(parts) == 2 and parts[1] == "recents.json":
                return self._send_json({"recents": list_recents()})
            if len(parts) == 2 and parts[1] == "latest.json":
                return self._send_json({"latest": list_latest()})
            if len(parts) == 2 and parts[1] == "health.json":
                return self._send_json(AUTH_HEALTH)
            if len(parts) == 2 and parts[1] == "metrics.json":
                return self._send_json(
                    STORE.totals() if STORE is not None else {}
                )
            if (
                len(parts) == 3
                and parts[1] == "sessions"
                and parts[2].endswith(".json")
            ):
                project_hash = parts[2][: -len(".json")]
                data = list_sessions(project_hash)
                if data is None:
                    return self.send_error(404, "project not found")
                return self._send_json({
                    "projectHash": project_hash,
                    "projectLabel": project_label(project_hash),
                    "sessions": data,
                })
            # /api/dashboard/<project>/<session>.json — return the per-chat
            # state (acks + persisted regen errors) plus the in-memory regen
            # status + file mtimes computed at request time. The dashboard
            # topnav polls this single endpoint so the status chip, the
            # error banner, and the rebuild button share one round-trip.
            if (
                len(parts) == 4
                and parts[1] == "dashboard"
                and parts[3].endswith(".json")
            ):
                project_hash = parts[2]
                session_uuid = parts[3][: -len(".json")]
                if not _PROJECT_HASH_RE.match(project_hash) or not _SESSION_UUID_RE.match(session_uuid):
                    return self.send_error(400, "invalid project or session id")
                if CHAT_STATE is None:
                    return self.send_error(503, "chat state not initialised")
                sidecar = CHAT_STATE.snapshot(project_hash, session_uuid)
                if sidecar is None:
                    return self.send_error(404, "session not found")
                # File mtimes — snapshot-only, no lock needed.
                jsonl_path = PROJECTS_ROOT / project_hash / f"{session_uuid}.jsonl"
                try:
                    jsonl_mtime = int(jsonl_path.stat().st_mtime)
                except OSError:
                    jsonl_mtime = None
                dash_html = PROJECTS_ROOT / project_hash / session_uuid / "dashboard.html"
                try:
                    dash_mtime = int(dash_html.stat().st_mtime)
                    has_dashboard = True
                except OSError:
                    dash_mtime = None
                    has_dashboard = False
                regen_state = (
                    REGISTRY.state_for(session_uuid)
                    if REGISTRY is not None else None
                )
                return self._send_json({
                    **sidecar,
                    "session": session_uuid,
                    "project": project_hash,
                    "hasDashboard": has_dashboard,
                    "mtime": jsonl_mtime,
                    "dashboardMtime": dash_mtime,
                    "lastTurnEndedAt": (
                        get_last_turn_end_cached(jsonl_path)
                        if jsonl_path.exists() else None
                    ),
                    "regen": regen_state,
                    "metrics": (
                        STORE.session_summary(session_uuid)
                        if STORE is not None else None
                    ),
                })
            return self.send_error(404, "unknown api endpoint")

        if parts[0] == "assets":
            asset_rel = "/".join(parts[1:])
            asset_path = (ASSETS_DIR / asset_rel).resolve()
            try:
                asset_path.relative_to(ASSETS_DIR.resolve())
            except ValueError:
                return self.send_error(403, "asset path escapes plugin dir")
            if not asset_path.is_file():
                return self.send_error(404, "asset not found")
            return self._serve_file(asset_path)

        # /<project-hash>/ → project-index template (overrides default index.html)
        if len(parts) == 1:
            if not (PROJECTS_ROOT / parts[0]).is_dir():
                return self.send_error(404, f"project '{parts[0]}' not found")
            # If this is a worktree project AND its parent dir exists, redirect
            # to the parent's index. Worktrees don't get their own index page;
            # their sessions are aggregated under the parent (see list_sessions).
            info = parse_project_hash(parts[0])
            if info["isWorktree"] and (PROJECTS_ROOT / info["parentHash"]).is_dir():
                self.send_response(301)
                self.send_header("Location", f"/{info['parentHash']}/")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if not path.endswith("/"):
                self.send_response(301)
                self.send_header("Location", f"/{parts[0]}/")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            return self._serve_template(
                "project-index.html",
                project_hash=parts[0],
                project_label=project_label(parts[0]),
            )

        # /<project-hash>/<session-uuid>/dashboard.html → fragment wrapped
        # with _layout.html, or legacy full document served as-is.
        if (
            len(parts) == 3
            and parts[2] == "dashboard.html"
            and (PROJECTS_ROOT / parts[0]).is_dir()
        ):
            if not _PROJECT_HASH_RE.match(parts[0]) or not _SESSION_UUID_RE.match(parts[1]):
                return self.send_error(400, "invalid project or session id")
            return self._serve_dashboard(parts[0], parts[1])

        # /<project-hash>/<file...> → a static file living inside a session dir
        # (e.g. an image a dashboard references). Locked down: never serve raw
        # .jsonl transcripts and never auto-list directories. The old catch-all
        # handed the entire projects tree — every transcript, plus directory
        # listings — straight to SimpleHTTPRequestHandler.
        return self._serve_project_static(parts)

    def _send_json(self, payload) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if getattr(self, "_head_only", False):
            return
        self.wfile.write(body)

    def _serve_file(self, p: Path) -> None:
        body = p.read_bytes()
        ext = p.suffix.lower()
        ct = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css",
            ".js": "application/javascript",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".json": "application/json",
            ".webmanifest": "application/manifest+json",
        }.get(ext, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if getattr(self, "_head_only", False):
            return
        self.wfile.write(body)

    def _serve_project_static(self, parts: "list") -> None:
        """Serve a static file from inside the projects tree, but never a raw
        transcript (.jsonl) and never a directory listing. Path traversal is
        contained by resolve() + relative_to(PROJECTS_ROOT)."""
        target = (PROJECTS_ROOT / "/".join(parts)).resolve()
        try:
            target.relative_to(PROJECTS_ROOT.resolve())
        except ValueError:
            return self.send_error(403, "path escapes projects root")
        if target.suffix.lower() == ".jsonl":
            return self.send_error(404, "not found")
        if not target.is_file():
            return self.send_error(404, "not found")
        return self._serve_file(target)

    def _serve_template(self, name: str, **substitutions) -> None:
        template = read_template(name)
        if not template:
            return self.send_error(500, f"template not found: {name}")
        body = apply_substitutions(template, substitutions).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if getattr(self, "_head_only", False):
            return
        self.wfile.write(body)

    def _serve_dashboard(self, project_hash: str, session_uuid: str) -> None:
        """Wrap a per-chat dashboard fragment with _layout.html. If the file
        on disk already starts with <!doctype>, it's a legacy full document
        and is served as-is via the static-file handler."""
        dash_path = (PROJECTS_ROOT / project_hash / session_uuid / "dashboard.html").resolve()
        try:
            dash_path.relative_to(PROJECTS_ROOT.resolve())
        except ValueError:
            return self.send_error(403, "path escapes projects root")
        if not dash_path.is_file():
            return self._serve_dashboard_placeholder(project_hash, session_uuid)

        # Track that the user opened this dashboard — but only for real GETs
        # (HEAD preflights and asset fetches don't represent a user view).
        if (
            STORE is not None
            and not getattr(self, "_head_only", False)
            and self.command == "GET"
        ):
            STORE.touch_open(project_hash, session_uuid)

        content = dash_path.read_text(encoding="utf-8", errors="replace")
        if content.lstrip().lower().startswith("<!doctype"):
            if getattr(self, "_head_only", False):
                return super().do_HEAD()
            return super().do_GET()

        layout = read_template("_layout.html")
        if not layout:
            return self.send_error(500, "layout template missing")

        body = apply_substitutions(layout, {
            "content": content,
            "session_title": extract_title(content, session_uuid),
            "session_uuid": session_uuid,
            "project_hash": project_hash,
            "project_label": project_label(project_hash),
        }).encode("utf-8")
        mtime = dash_path.stat().st_mtime

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header(
            "Last-Modified",
            time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(mtime)),
        )
        self.end_headers()
        if getattr(self, "_head_only", False):
            return
        self.wfile.write(body)

    def _serve_dashboard_placeholder(self, project_hash: str, session_uuid: str) -> None:
        """No dashboard.html yet — never generated, or the first attempt failed.

        Serve the _layout shell anyway instead of a bare 404. Its topnav polls
        /api/dashboard/<h>/<s>.json, so the regen-error banner and freshness
        chip surface the failure (e.g. 'Credit balance is too low'), and the
        page auto-reloads into the real dashboard once one lands. A 404 here is
        exactly what made a failed first-gen invisible."""
        layout = read_template("_layout.html")
        if not layout:
            return self.send_error(500, "layout template missing")
        content = (
            '<header class="session-header"><h1>Dashboard pending</h1>'
            '<p style="color:var(--muted)">No dashboard has been generated for '
            'this chat yet.</p></header>'
            '<section style="color:var(--muted);font-size:0.9rem;line-height:1.6;'
            'padding:0.5rem 0">If a generation attempt failed, the reason is in '
            'the banner above. Otherwise it appears automatically once the next '
            'turn completes — or press <strong>↻ rebuild</strong> to generate it '
            'now.</section>'
        )
        body = apply_substitutions(layout, {
            "content": content,
            "session_title": "Dashboard pending",
            "session_uuid": session_uuid,
            "project_hash": project_hash,
            "project_label": project_label(project_hash),
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if getattr(self, "_head_only", False):
            return
        self.wfile.write(body)


def main() -> int:
    log_path = configure_logging(RUNTIME_DIR)

    regen_model = os.environ.get("CCD_MODEL") or DEFAULT_MODEL
    regen_n_turns = _env_int("CCD_N_TURNS", DEFAULT_N_TURNS)
    regen_max_words = _env_int("CCD_MAX_TRANSCRIPT_WORDS", DEFAULT_MAX_TRANSCRIPT_WORDS, minimum=0)
    regen_timeout = _env_float("CCD_REGEN_TIMEOUT", DEFAULT_REGEN_TIMEOUT)

    if not PROJECTS_ROOT.is_dir():
        _log.error("CLAUDE_PROJECTS_DIR not found: %s", PROJECTS_ROOT)
        return 1
    if not TEMPLATES_DIR.is_dir():
        _log.error("templates dir not found: %s", TEMPLATES_DIR)
        return 1

    global REGISTRY, STORE, CHAT_STATE
    STORE = DashboardStore(RUNTIME_DIR / "dashboard.db")
    CHAT_STATE = ChatState(projects_root=PROJECTS_ROOT)

    def _on_regen_failure(project_hash: str, session_uuid: str,
                          kind: str, message: str) -> None:
        entry = CHAT_STATE.record_error(
            project_hash, session_uuid, kind=kind, message=message,
        )
        if entry is not None:
            _log.info(
                "regen error persisted %s/%s id=%s kind=%s",
                project_hash, session_uuid[:8], entry["id"], kind,
            )

    # on_success → touch recents so child agent dashboards auto-surface
    # in the quick-jump strip the moment their first turn completes.
    # on_failure → persist the error in the per-chat state.json so the
    # user can find and dismiss it deliberately (not via 8-second toast).
    REGISTRY = Registry(
        plugin_dir=PLUGIN_DIR,
        projects_root=PROJECTS_ROOT,
        model=regen_model,
        n_turns=regen_n_turns,
        timeout=regen_timeout,
        max_words=regen_max_words,
        metrics=STORE,
        on_success=STORE.touch_open,
        on_failure=_on_regen_failure,
    )

    # Startup auth health probe (daemon — never block server start on it). The
    # regen subagent runs on the Claude Code subscription by policy; this checks
    # it can actually authenticate, so a broken/billing state shows up loudly
    # in the log and at /api/health.json instead of as silently-missing
    # dashboards. See regen.build_subagent_env / probe_auth.
    def _run_auth_probe() -> None:
        ok, detail = probe_auth()
        AUTH_HEALTH["regenAuth"] = "ok" if ok else "failed"
        AUTH_HEALTH["detail"] = detail
        AUTH_HEALTH["checkedAt"] = int(time.time())
        if ok:
            _log.info("startup auth probe: OK — regen can authenticate")
        else:
            _log.warning(
                "startup auth probe FAILED — new dashboards will NOT generate: %s",
                detail,
            )

    threading.Thread(target=_run_auth_probe, name="auth-probe", daemon=True).start()

    _log.info("claude-dashboard server starting")
    _log.info(
        "  AUTH MODE     = Claude Code subscription (ambient %s ignored)",
        "/".join(AMBIENT_AUTH_VARS),
    )
    _log.info("  PROJECTS_ROOT = %s", PROJECTS_ROOT)
    _log.info("  PLUGIN_DIR    = %s", PLUGIN_DIR)
    _log.info("  URL           = http://localhost:%d/", PORT)
    _log.info("  LOG           = %s", log_path)
    _log.info("  MODEL         = %s  (n_turns=%d, timeout=%.0fs, max_words=%d)",
              regen_model, regen_n_turns, regen_timeout, regen_max_words)
    sys.stdout.flush()

    try:
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError as e:
        print(f"ERROR: cannot bind 127.0.0.1:{PORT}: {e}\n"
              f"  The port may be in use. Set PORT in the plugin's .env to a free port.",
              file=sys.stderr)
        _log.error("bind failed on 127.0.0.1:%d: %s", PORT, e)
        return 1
    httpd.daemon_threads = True

    # Publish the bound port so the Stop hook — which runs inside Claude Code's
    # process, outside atk's env injection — can discover it via DASHBOARD_PORT_FILE.
    try:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        (RUNTIME_DIR / "port").write_text(str(httpd.server_address[1]))
    except OSError as e:
        _log.warning("could not write runtime/port: %s", e)

    with httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            _log.info("shutting down")
    return 0


if __name__ == "__main__":
    sys.exit(main())
