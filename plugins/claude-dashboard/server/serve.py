#!/usr/bin/env python3
"""HTTP server for the Claude Code chat dashboards: browse pages, per-chat
dashboards, the JSON APIs, and the regen trigger, on one loopback port."""

import hashlib
import html
import http.server
import json
import os
import re
import sys
import threading
import time
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import identity
from chat_state import ChatState
from config import Settings
from failures import present as present_failure
from logging_config import configure_logging, get_logger, set_log_level
from regen import AMBIENT_AUTH_VARS, Registry, probe_auth
from store import DashboardStore

PORT = int(os.environ.get("PORT", 7878))
PROJECTS_ROOT = Path(
    os.environ.get("CLAUDE_PROJECTS_DIR")
    or (Path.home() / ".claude" / "projects")
)
PLUGIN_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = PLUGIN_DIR / "templates"
ASSETS_DIR = PLUGIN_DIR / "assets"
RUNTIME_DIR = PLUGIN_DIR / "runtime"

_log = get_logger("serve")


# Initialised in main() so importing this module has no side effects.
REGISTRY: "Registry | None" = None
STORE: "DashboardStore | None" = None
CHAT_STATE: "ChatState | None" = None
SETTINGS = Settings(PLUGIN_DIR / ".env")

# Stats-page range selector → (lookback seconds or None for all, time bucket).
_STATS_RANGES = {
    "1d": (86_400, "hour"),
    "7d": (7 * 86_400, "day"),
    "30d": (30 * 86_400, "day"),
    "all": (None, "day"),
}

# Filled by the startup probe in main(); served at /api/health.json.
AUTH_HEALTH: dict = {"regenAuth": None, "detail": "probe not run yet", "checkedAt": None}

class _MtimeCache:
    """Memoise a per-file computation keyed on (path, mtime). Entries turn over
    when the file gets new writes and are evicted when it disappears, so
    deleted chats don't pin memory."""

    def __init__(self, compute, missing=None):
        self._compute = compute
        self._missing = missing
        self._entries: "dict[str, dict]" = {}
        self._lock = threading.Lock()

    def get(self, path: Path):
        key = str(path)
        try:
            mtime = path.stat().st_mtime
        except OSError:
            with self._lock:
                self._entries.pop(key, None)
            return self._missing
        with self._lock:
            entry = self._entries.get(key)
            if entry and entry["mtime"] == mtime:
                return entry["value"]
        value = self._compute(path)
        with self._lock:
            self._entries[key] = {"mtime": mtime, "value": value}
        return value


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(epoch))


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


_META_CACHE = _MtimeCache(parse_session_meta, missing={})


_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.DOTALL | re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


# ─── Last-completed-turn detection ─────────────────────────────────────


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
    """True iff this user event is a typed message, not a tool_result carried
    on a user-role line."""
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
    """True iff `ev` is a text-only assistant message followed by EOF or a
    user-typed message. The lookahead keeps a mid-turn "Let me check…" text
    block before a tool_use from counting as a turn end."""
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
    return next_ev is None or _is_user_typed_message(next_ev)


def _scan_last_turn_end(jsonl_path: Path) -> "int | None":
    """Walk the JSONL backwards in 64 KB chunks; return the epoch of the most
    recent assistant event that closed a turn."""
    try:
        size = jsonl_path.stat().st_size
    except OSError:
        return None
    if size == 0:
        return None

    chunk_size = 65536
    leftover = b""
    pos = size
    next_ev: "dict | None" = None  # chronologically newer than the current event

    with jsonl_path.open("rb") as fh:
        while pos > 0:
            read_size = min(chunk_size, pos)
            pos -= read_size
            fh.seek(pos)
            data = fh.read(read_size) + leftover
            lines = data.split(b"\n")
            # With more file before this chunk, the first element is a line
            # fragment that continues in the previous chunk.
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


_LAST_TURN_CACHE = _MtimeCache(_scan_last_turn_end)
_ANCHOR_CACHE = _MtimeCache(
    identity.session_anchor, missing={"cwd": None, "gitBranch": None})


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
    """Replace `{{key}}` placeholders. `{{shared_head}}` and `{{shared_nav}}`
    always pull templates/_head.html and _nav.html so every page renders the
    same head bits and the same nav menu."""
    out = template.replace("{{shared_head}}", read_template("_head.html"))
    out = out.replace("{{shared_nav}}", read_template("_nav.html"))
    for k, v in substitutions.items():
        out = out.replace(f"{{{{{k}}}}}", str(v))
    return out


def _breadcrumb(*parts: "tuple[str, str | None]") -> str:
    """Build the nav breadcrumb from (label, href) pairs in order. The last
    pair, and any with href None, renders as plain text (the current page)."""
    sep = '<span class="sep">›</span>'
    crumbs = []
    for i, (label, href) in enumerate(parts):
        if href and i != len(parts) - 1:
            crumbs.append(f'<a href="{html.escape(href, quote=True)}">{html.escape(label)}</a>')
        else:
            crumbs.append(f'<span class="here">{html.escape(label)}</span>')
    return sep.join(crumbs)


# The app's top-level sections, declared once. This list renders the menu and
# marks which entry is current. Projects, Stats and Settings are siblings; a
# chat lives under Projects, but Stats and Settings do not. Adding a page means
# one line here plus its route.
SECTIONS = (
    ("projects", "Projects", "/"),
    ("stats", "Stats", "/stats"),
    ("settings", "Settings", "/settings"),
)


def _nav_items(active: str) -> str:
    """Render the menu entries, marking the section the current page belongs to.
    The server already knows which page it is serving, so nothing has to infer
    it from the URL on the client."""
    return "\n    ".join(
        f'<a role="menuitem" class="appmenu-item{" on" if key == active else ""}"'
        f' href="{html.escape(href, quote=True)}">{html.escape(label)}</a>'
        for key, label, href in SECTIONS
    )


def _page_chrome(content: str, *, page_title: str, subtitle: str,
                 meta_extra: str = "", footer: str = "",
                 wrap_class: str = "", strip: bool = False) -> str:
    """The browse pages' shared shell: wrap, header with status chip and
    Updated stamp, footer. `subtitle`/`meta_extra`/`footer` are server-authored
    HTML."""
    wrap = f"wrap {wrap_class}".strip()
    strip_html = (
        '<div class="recents-strip recents-strip--inline" id="recents-strip"></div>\n'
        if strip else ""
    )
    return (
        f'<div class="{wrap}">\n'
        f"{strip_html}"
        '<header class="page">\n'
        "  <div>\n"
        f"    <h1>{html.escape(page_title)}</h1>\n"
        f'    <div class="subtitle">{subtitle}</div>\n'
        "  </div>\n"
        '  <div class="meta">\n'
        f"    {meta_extra}"
        '<span class="status live" id="status" role="status"><span class="dot"></span>live</span><br/>\n'
        '    Updated <span id="updated">–</span>\n'
        "  </div>\n"
        "</header>\n"
        f"{content}\n"
        f"<footer>{footer}</footer>\n"
        "</div>"
    )


def render_page(content_template: str, *, title: str, breadcrumb: str,
                section: str = "", body_class: str = "", nav_actions: str = "",
                page: "dict | None" = None, **content_subs) -> bytes:
    """Wrap a content-only template in base.html. base.html owns the <head>,
    the app-nav bar, and the menu; `section` marks the current menu entry.
    `page`, when given, wraps the content in the browse pages' shared shell
    (_page_chrome kwargs). Returns the document as UTF-8 bytes."""
    content = apply_substitutions(read_template(content_template), content_subs)
    if page is not None:
        content = _page_chrome(content, **page)
    doc = apply_substitutions(read_template("base.html"), {
        "title": title,
        "body_class": body_class,
        "breadcrumb": breadcrumb,
        "nav_actions": nav_actions,
        "nav_items": _nav_items(section),
        "content": content,
    })
    return doc.encode("utf-8")


# Worktree project dirs are named <parent-hash>--claude-worktrees-<name>-<hash>.
WT_MARKER = "--claude-worktrees-"


def parse_project_hash(project_hash: str) -> dict:
    """Extract worktree-vs-parent info from a project-hash dir name."""
    if WT_MARKER in project_hash:
        parent_hash, wt_part = project_hash.split(WT_MARKER, 1)
        parent_parts = [p for p in parent_hash.split("-") if p]
        parent_label = parent_parts[-1] if parent_parts else parent_hash
        wt_segments = [s for s in wt_part.split("-") if s]
        # wt_part is "<adjective>-<noun>-<6char-hash>".
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


# Sessions are grouped by their REAL project (git repo root or plain folder),
# derived from each transcript's cwd (identity.py). The slug dir remains the
# storage and URL key; grouping is presentation only. Recomputed at most every
# _GROUPS_TTL_S; anchors and root resolutions have their own caches.
_GROUPS_TTL_S = 3.0
_GROUPS_CACHE: dict = {"at": 0.0, "value": None}


def _compute_groups() -> dict:
    """Map every session to its group.

    Returns {"session_group": {(slug, uuid): key},
             "groups": {key: {label, rootPath, slugs, repr, member_tags}}}.
    Keys look like "repo:<path>", "dir:<path>", or "slug:<slug>"."""
    sessions = []
    if PROJECTS_ROOT.is_dir():
        for proj_dir in PROJECTS_ROOT.iterdir():
            if not proj_dir.is_dir():
                continue
            for jsonl in proj_dir.glob("*.jsonl"):
                anchor = _ANCHOR_CACHE.get(jsonl)
                sessions.append((proj_dir.name, jsonl.stem, anchor.get("cwd")))

    live_index: "dict[str, dict | None]" = {}
    for _, _, cwd in sessions:
        if cwd and cwd not in live_index:
            live_index[cwd] = identity.resolve_root_cached(cwd)

    session_group: dict = {}
    live_keys_by_slug: "dict[str, Counter]" = {}
    member_tag: dict = {}  # (key, slug) -> worktree-ish tag for sub-entries
    dead: list = []
    for slug, uuid, cwd in sessions:
        r = live_index.get(cwd) if cwd else None
        if r is None:
            dead.append((slug, uuid, cwd))
            continue
        key = f"{r['kind']}:{r['root']}"
        session_group[(slug, uuid)] = key
        live_keys_by_slug.setdefault(slug, Counter())[key] += 1
        if r["isWorktree"] and r["worktreeDir"]:
            member_tag.setdefault((key, slug), Path(r["worktreeDir"]).name)

    dead_labels: "dict[str, Counter]" = {}
    for slug, uuid, cwd in dead:
        key = None
        if cwd:
            root = identity.rescue_dead(cwd, live_index)
            if root is not None:
                key = f"repo:{root}"
                member_tag.setdefault((key, slug), Path(cwd).name)
        if key is None:
            # The slug dir itself is evidence: adopt where its resolvable
            # sessions went (covers resumed-in-a-now-deleted-worktree chats).
            counts = live_keys_by_slug.get(slug)
            if counts:
                key = counts.most_common(1)[0][0]
        if key is None:
            info = parse_project_hash(slug)
            if info["isWorktree"]:
                key = f"slug:{info['parentHash']}"
                member_tag.setdefault((key, slug), info["worktreeName"])
            else:
                key = f"slug:{slug}"
            if cwd and identity.valid_cwd(cwd):
                # The transcript still knows the deleted folder's real path;
                # it beats the slug's ambiguous last dash-segment.
                dead_labels.setdefault(key, Counter())[cwd] += 1
        session_group[(slug, uuid)] = key

    groups: dict = {}
    for (slug, _), key in session_group.items():
        groups.setdefault(key, {"slugs": set()})["slugs"].add(slug)
    for key, g in groups.items():
        kind, _, val = key.partition(":")
        if kind == "slug":
            votes = dead_labels.get(key)
            if votes:
                dead_path = votes.most_common(1)[0][0]
                g["label"] = Path(dead_path).name
                g["rootPath"] = dead_path
            else:
                g["label"] = project_label(val)
                g["rootPath"] = None
            preferred = val
        else:
            g["label"] = Path(val).name or val
            g["rootPath"] = val
            preferred = identity.slug_for_path(val)
        g["repr"] = preferred if preferred in g["slugs"] else min(g["slugs"])
        g["member_tags"] = {
            slug: tag for (k, slug), tag in member_tag.items() if k == key
        }
    return {"session_group": session_group, "groups": groups,
            "live_index": live_index}


def project_groups(force: bool = False) -> dict:
    now = time.monotonic()
    if (force or _GROUPS_CACHE["value"] is None
            or now - _GROUPS_CACHE["at"] > _GROUPS_TTL_S):
        _GROUPS_CACHE["value"] = _compute_groups()
        _GROUPS_CACHE["at"] = now
    return _GROUPS_CACHE["value"]


def _group_of_slug(gm: dict, slug: str) -> "str | None":
    """The group key a slug's page represents: the group it fronts, else
    any group it contributes sessions to."""
    for key, g in gm["groups"].items():
        if g["repr"] == slug:
            return key
    for key, g in gm["groups"].items():
        if slug in g["slugs"]:
            return key
    return None


def _group_label_for(slug: str, uuid: str) -> str:
    gm = project_groups()
    key = gm["session_group"].get((slug, uuid))
    if key is None:
        return project_label(slug)
    return gm["groups"][key]["label"]


def _member_sub_tag(gm: dict, key: str, slug: str) -> str:
    tag = gm["groups"][key]["member_tags"].get(slug)
    if tag:
        return tag
    info = parse_project_hash(slug)
    return info["worktreeName"] or project_label(slug)


def list_projects() -> list:
    """One card per real project; member slug dirs fold in as sub-entries."""
    if not PROJECTS_ROOT.is_dir():
        return []
    gm = project_groups()
    for attempt in range(2):
        per_group: dict = {}
        stale = False
        for proj_dir in PROJECTS_ROOT.iterdir():
            if not proj_dir.is_dir():
                continue
            slug = proj_dir.name
            for jsonl in proj_dir.glob("*.jsonl"):
                key = gm["session_group"].get((slug, jsonl.stem))
                if key is None:
                    stale = True
                    continue
                try:
                    mtime = jsonl.stat().st_mtime
                except OSError:
                    continue
                has_dash = (proj_dir / jsonl.stem / "dashboard.html").is_file()
                e = per_group.setdefault(
                    key, {"chats": 0, "dash": 0, "latest": 0.0, "by_slug": {}})
                e["chats"] += 1
                e["dash"] += int(has_dash)
                e["latest"] = max(e["latest"], mtime)
                s = e["by_slug"].setdefault(
                    slug, {"chats": 0, "dash": 0, "latest": 0.0})
                s["chats"] += 1
                s["dash"] += int(has_dash)
                s["latest"] = max(s["latest"], mtime)
        if not stale or attempt == 1:
            break
        gm = project_groups(force=True)  # a chat appeared inside the TTL window

    final = []
    for key, e in per_group.items():
        g = gm["groups"][key]
        repr_slug = g["repr"] if g["repr"] in e["by_slug"] else max(
            e["by_slug"], key=lambda s: e["by_slug"][s]["latest"])
        members = [
            {
                "hash": slug,
                "worktreeName": _member_sub_tag(gm, key, slug),
                "chatCount": v["chats"],
                "withDashboards": v["dash"],
                "lastActivity": int(v["latest"]),
                "lastActivityIso": _iso(v["latest"]),
            }
            for slug, v in e["by_slug"].items() if slug != repr_slug
        ]
        members.sort(key=lambda w: w["lastActivity"], reverse=True)
        final.append({
            "hash": repr_slug,
            "label": g["label"],
            "rootPath": g["rootPath"],
            "chatCount": e["chats"],
            "withDashboards": e["dash"],
            "lastActivity": int(e["latest"]),
            "lastActivityIso": _iso(e["latest"]),
            "isWorktree": False,
            "parentHash": None,
            "worktreeName": None,
            "worktrees": members,
        })
    final.sort(key=lambda p: p["lastActivity"], reverse=True)
    return final


def _session_row(
    source_dir: Path,
    jsonl: Path,
    worktree_name: "str | None",
) -> "dict | None":
    """The row shape /api/sessions and /api/recents emit for one session
    JSONL, or None if it is unreadable."""
    uuid = jsonl.stem
    try:
        st = jsonl.stat()
    except OSError:
        return None
    meta = _META_CACHE.get(jsonl)
    dash_path = source_dir / uuid / "dashboard.html"
    has_dashboard = dash_path.is_file()
    dash_mtime = None
    if has_dashboard:
        try:
            dash_mtime = int(dash_path.stat().st_mtime)
        except OSError:
            pass
    regen_state = REGISTRY.state_for(uuid) if REGISTRY is not None else None
    # Persisted errors let a failed first generation show a chip even though
    # no dashboard.html exists and a restart cleared the in-memory record.
    regen_errors: list = []
    if CHAT_STATE is not None:
        snap = CHAT_STATE.snapshot(source_dir.name, uuid)
        if snap is not None:
            regen_errors = snap.get("regenErrors", [])
    return {
        "uuid": uuid,
        "shortUuid": uuid[:8],
        "mtime": int(st.st_mtime),
        "mtimeIso": _iso(st.st_mtime),
        "size": st.st_size,
        "aiTitle": meta.get("aiTitle", ""),
        "firstUser": meta.get("firstUser", ""),
        "hasDashboard": has_dashboard,
        "dashboardMtime": dash_mtime,
        "lastTurnEndedAt": _LAST_TURN_CACHE.get(jsonl),
        "regen": regen_state,
        "regenErrors": regen_errors,
        "sourceHash": source_dir.name,
        "worktreeName": worktree_name,
    }


def _scan_sessions(source_dir: Path, worktree_name: "str | None", rows: list) -> None:
    """Append session rows from one project dir into `rows`."""
    for jsonl in sorted(source_dir.glob("*.jsonl")):
        row = _session_row(source_dir, jsonl, worktree_name)
        if row is not None:
            rows.append(row)


def list_recents() -> list:
    """The recents queue as enriched session rows; an entry whose JSONL is
    gone is dropped and forgotten."""
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
        row["projectLabel"] = _group_label_for(proj, sess)
        out.append(row)
    return out


def list_latest(limit: int = 15) -> list:
    """Every session with a dashboard, across all projects, freshest first."""
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
            row["projectLabel"] = _group_label_for(proj_dir.name, jsonl.stem)
            rows.append(row)

    def _freshness(r: dict) -> int:
        return max(r.get("dashboardMtime") or 0, r.get("lastTurnEndedAt") or 0)

    rows.sort(key=_freshness, reverse=True)
    return rows[:limit]


def _session_wt_tag(gm: dict, slug: str, jsonl: Path, key: str) -> "str | None":
    """A worktree session's inline tag: its branch, falling back to the
    worktree dir name; None for sessions in the main checkout."""
    anchor = _ANCHOR_CACHE.get(jsonl)
    cwd = anchor.get("cwd")
    r = identity.resolve_root_cached(cwd) if cwd else None
    if r is not None:
        if not r["isWorktree"]:
            return None
        return anchor.get("gitBranch") or Path(r["worktreeDir"]).name
    if cwd and key.startswith("repo:"):  # dead worktree, rescued into the repo
        return anchor.get("gitBranch") or Path(cwd).name
    info = parse_project_hash(slug)
    return info["worktreeName"]


def list_sessions(project_hash: str):
    """Sessions for a project card: every session grouped with this slug,
    across all member slug dirs."""
    proj_dir = PROJECTS_ROOT / project_hash
    if not proj_dir.is_dir():
        return None
    gm = project_groups()
    key = _group_of_slug(gm, project_hash)
    if key is None:
        # Not in the group snapshot (e.g. brand-new dir): serve it alone.
        rows: list = []
        _scan_sessions(proj_dir, None, rows)
        rows.sort(key=lambda r: r["mtime"], reverse=True)
        return rows
    rows = []
    for slug in sorted(gm["groups"][key]["slugs"]):
        sdir = PROJECTS_ROOT / slug
        if not sdir.is_dir():
            continue
        for jsonl in sorted(sdir.glob("*.jsonl")):
            if gm["session_group"].get((slug, jsonl.stem)) != key:
                continue
            row = _session_row(sdir, jsonl, _session_wt_tag(gm, slug, jsonl, key))
            if row is not None:
                rows.append(row)
    rows.sort(key=lambda r: r["mtime"], reverse=True)
    return rows


def rebucket_stats_projects(rows: list) -> list:
    """Merge by-project telemetry rows (keyed by historical slugs) into the
    live groups; slugs that no longer resolve keep their own row with
    today's last-segment label."""
    gm = project_groups()
    slug_key: "dict[str, Counter]" = {}
    for (slug, _), key in gm["session_group"].items():
        slug_key.setdefault(slug, Counter())[key] += 1

    def _key_for_slug(slug: str) -> "str | None":
        counts = slug_key.get(slug)
        if counts:
            return counts.most_common(1)[0][0]
        info = parse_project_hash(slug)
        if info["isWorktree"]:
            parent = slug_key.get(info["parentHash"])
            if parent:
                return parent.most_common(1)[0][0]
        # A dir left behind by subagent spawns has no top-level chat, but its
        # subagent transcripts still carry the cwd.
        proj_dir = PROJECTS_ROOT / slug
        if proj_dir.is_dir():
            sub = next(proj_dir.glob("*/subagents/**/*.jsonl"), None)
            if sub is not None:
                cwd = identity.session_anchor(
                    sub, include_sidechain=True).get("cwd")
                r = identity.resolve_root_cached(cwd) if cwd else None
                if r is not None:
                    return f"{r['kind']}:{r['root']}"
                if cwd:
                    root = identity.rescue_dead(cwd, gm["live_index"])
                    if root is not None:
                        return f"repo:{root}"
        return None

    merged: dict = {}
    for r in rows:
        slug = str(r.get("project", ""))
        key = _key_for_slug(slug)
        if key is not None and key not in gm["groups"]:
            key = None  # resolvable, but no live group to merge into
        if key is not None:
            label = gm["groups"][key]["label"]
            project = gm["groups"][key]["repr"]
        else:
            label = project_label(slug)
            project = slug
        m = merged.setdefault(key or f"slug:{slug}", {
            "project": project, "label": label, "regens": 0,
            "failed": 0, "superseded": 0, "cost_usd": 0.0, "_wall_sum": 0.0,
        })
        regens = int(r.get("regens") or 0)
        m["regens"] += regens
        m["failed"] += int(r.get("failed") or 0)
        m["superseded"] += int(r.get("superseded") or 0)
        m["cost_usd"] += float(r.get("cost_usd") or 0.0)
        m["_wall_sum"] += float(r.get("avg_wall_s") or 0.0) * regens
    out = []
    for m in merged.values():
        wall_sum = m.pop("_wall_sum")
        m["avg_wall_s"] = (wall_sum / m["regens"]) if m["regens"] else 0.0
        out.append(m)
    out.sort(key=lambda m: m["cost_usd"], reverse=True)
    return out


# URL path segments are validated before they reach ChatState or the filesystem.
_SESSION_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
# Project-hash dirs are sanitised paths starting with `-`; the tight charset
# lets them be stitched straight into PROJECTS_ROOT / <hash> / …
_PROJECT_HASH_RE = re.compile(r"^-[a-zA-Z0-9_\-]{1,255}$")

# The CSP contains a prompt-injected fragment, not remote attackers: anything
# visual may render (inline script/style, SVG, Mermaid via jsdelivr), but every
# channel that could send transcript content to an external origin is denied.
_CSP = (
    "default-src 'none'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self' data:; "
    "media-src 'self' data:; "
    "manifest-src 'self'; "
    "connect-src 'self'; "
    "form-action 'none'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'"
)


def _is_error_ack_path(parts: list) -> bool:
    """/api/dashboard/<project>/<session>/error/<id>/acknowledge"""
    return (
        len(parts) == 7
        and parts[0] == "api"
        and parts[1] == "dashboard"
        and parts[4] == "error"
        and parts[6] == "acknowledge"
    )


class Handler(http.server.SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PROJECTS_ROOT), **kwargs)

    def _respond(self, body: bytes, content_type: str, status: int = 200,
                 headers: "dict | None" = None) -> None:
        """Write one complete response; body is suppressed on HEAD."""
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if not getattr(self, "_head_only", False):
            self.wfile.write(body)

    def _redirect(self, location: str) -> None:
        self.send_response(301)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _guard_chat_route(self, project_hash: str, session_uuid: str) -> bool:
        """Shared validation for per-chat routes: 400 on malformed ids, 503
        while chat state isn't initialised. True means proceed."""
        if not _PROJECT_HASH_RE.match(project_hash) or not _SESSION_UUID_RE.match(session_uuid):
            self.send_error(400, "invalid project or session id")
            return False
        if CHAT_STATE is None:
            self.send_error(503, "chat state not initialised")
            return False
        return True

    def end_headers(self):
        # Deliberately no CORS headers: every consumer is same-origin, and the
        # absence blocks cross-origin reads and preflighted POSTs.
        self.send_header("Content-Security-Policy", _CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_error(self, code, message=None, explain=None):
        """Branded error page for browser routes; the default terse handler
        for /api/ paths and HEAD requests."""
        path = urlparse(self.path).path if getattr(self, "path", None) else "/"
        if path.startswith("/api/") or getattr(self, "_head_only", False):
            return super().send_error(code, message)
        label = {400: "Bad request", 403: "Forbidden", 404: "Not found"}.get(code, "Error")
        try:
            body = render_page(
                "_error.html",
                title=f"{code} {label}",
                section="projects",
                breadcrumb=_breadcrumb(("Projects", "/"), (label, None)),
                code=str(code), label=html.escape(label),
                message=html.escape(message or ""),
            )
        except Exception:
            return super().send_error(code, message)
        self._respond(body, "text/html; charset=utf-8", status=code)

    def log_message(self, fmt, *args):
        sys.stderr.write(
            f"[{time.strftime('%H:%M:%S')}] {self.address_string()} {fmt % args}\n"
        )

    def _require_json(self) -> bool:
        """The CSRF guard: requiring a JSON content type forces cross-origin
        callers into a CORS preflight this server never satisfies."""
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
        if len(parts) == 2 and parts[0] == "api" and parts[1] == "regen":
            return self._handle_regen_post()
        if len(parts) == 2 and parts[0] == "api" and parts[1] == "settings.json":
            return self._handle_settings_post()
        if _is_error_ack_path(parts):
            return self._handle_error_ack("POST")
        return self._handle_ack_mutation("POST")

    def do_DELETE(self):
        if not self._require_json():
            return
        path = urlparse(self.path).path
        parts = [p for p in path.split("/") if p]
        if _is_error_ack_path(parts):
            return self._handle_error_ack("DELETE")
        return self._handle_ack_mutation("DELETE")

    def _read_json_body(self, max_bytes: int = 4096) -> "dict | None":
        """Parse a small JSON body; None on any error."""
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
        if not _PROJECT_HASH_RE.match(project_hash):
            return self.send_error(400, "invalid 'project' hash")
        jsonl = PROJECTS_ROOT / project_hash / f"{session_uuid}.jsonl"
        if not jsonl.is_file():
            return self.send_error(404, "session jsonl not found")
        state = REGISTRY.trigger(project_hash, session_uuid)
        body_bytes = json.dumps({
            "ok": True,
            "project": project_hash,
            "session": session_uuid,
            "regen": state,
        }).encode("utf-8")
        self._respond(body_bytes, "application/json; charset=utf-8", status=202)

    def do_HEAD(self):
        # HEAD routes through do_GET with body writes suppressed; the parent's
        # default do_HEAD would look for /assets/* under PROJECTS_ROOT and 404.
        self._head_only = True
        try:
            self.do_GET()
        finally:
            self._head_only = False

    def _handle_ack_mutation(self, method: str) -> None:
        """POST/DELETE /api/dashboard/<project>/<session>/acknowledge/<row>:
        toggle a heads-up row's acknowledged state."""
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
        if not self._guard_chat_route(project_hash, session_uuid):
            return
        if not ChatState.is_valid_row_id(row_id):
            return self.send_error(400, "invalid row id")
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
        """POST/DELETE /api/dashboard/<project>/<session>/error/<id>/acknowledge:
        flip a persisted regen error's ackedAt; the entry itself stays."""
        path = urlparse(self.path).path
        parts = [p for p in path.split("/") if p]
        if not _is_error_ack_path(parts):
            return self.send_error(404, "unknown endpoint")
        project_hash, session_uuid, error_id = parts[2], parts[3], parts[5]
        if not self._guard_chat_route(project_hash, session_uuid):
            return
        if not ChatState.is_valid_error_id(error_id):
            return self.send_error(400, "invalid error id")
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
            return self._respond(
                render_page("projects-landing.html",
                            title="Claude Code · projects",
                            section="projects",
                            breadcrumb=_breadcrumb(("Projects", None)),
                            page=dict(
                                page_title="Claude Code · projects",
                                subtitle="All projects with chat history · click one to see its chats",
                                meta_extra="Served by <code>claude-dashboard</code><br/>\n    ",
                                footer='Auto-refreshes every 30s · <code>/api/projects.json</code>'
                                       '<span id="metrics-total"></span>',
                                strip=True,
                            )),
                "text/html; charset=utf-8")

        if parts == ["stats"]:
            return self._respond(
                render_page("stats.html",
                            title="Claude Code · generation stats",
                            section="stats",
                            breadcrumb=_breadcrumb(("Stats", None)),
                            page=dict(
                                page_title="Generation stats",
                                subtitle="Every <code>claude -p</code> regen the server has run",
                                wrap_class="wrap--wide",
                            )),
                "text/html; charset=utf-8")

        if parts == ["settings"]:
            return self._respond(
                render_page("settings.html",
                            title="Claude Code · settings",
                            section="settings",
                            breadcrumb=_breadcrumb(("Settings", None)),
                            page=dict(
                                page_title="Settings",
                                subtitle="Changes apply right away and are saved for next time",
                                footer="<code>/api/settings.json</code>",
                                wrap_class="wrap--narrow",
                            )),
                "text/html; charset=utf-8")

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
            if len(parts) == 2 and parts[1] == "stats.json":
                return self._serve_stats()
            if len(parts) == 2 and parts[1] == "settings.json":
                return self._send_json({
                    "settings": SETTINGS.public(),
                    "readonly": {"port": PORT, "projects_dir": str(PROJECTS_ROOT)},
                })
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
            # /api/dashboard/<project>/<session>.json: per-chat state plus
            # regen status and file mtimes, in the one round-trip the
            # dashboard shell polls.
            if (
                len(parts) == 4
                and parts[1] == "dashboard"
                and parts[3].endswith(".json")
            ):
                project_hash = parts[2]
                session_uuid = parts[3][: -len(".json")]
                if not self._guard_chat_route(project_hash, session_uuid):
                    return
                sidecar = CHAT_STATE.snapshot(project_hash, session_uuid)
                jsonl_path = PROJECTS_ROOT / project_hash / f"{session_uuid}.jsonl"
                if sidecar is None:
                    # A brand-new chat has a transcript but no session dir yet;
                    # it still gets an empty state, and 404 only when the chat
                    # itself does not exist.
                    if not jsonl_path.is_file():
                        return self.send_error(404, "session not found")
                    sidecar = ChatState.empty_state()
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
                metrics = (
                    STORE.session_summary(session_uuid) if STORE is not None else None
                )
                # Failures are stored raw; failures.present decides at read time
                # how each one reads, with this chat's live numbers.
                typical_s = None
                if metrics and metrics.get("avg_wall_ms"):
                    typical_s = metrics["avg_wall_ms"] / 1000.0
                presented_errors = [
                    {**entry, "presentation": present_failure(
                        entry.get("kind", ""), entry.get("message", ""),
                        timeout_s=SETTINGS.get("CCD_REGEN_TIMEOUT"),
                        typical_s=typical_s,
                        measurements=(
                            STORE.failure_row(session_uuid, entry.get("at") or 0)
                            if STORE is not None else {}
                        ),
                    )}
                    for entry in (sidecar.get("regenErrors") or [])
                ]
                # The DashboardModel stays server-side; the shell polls this
                # endpoint every couple of seconds and never reads it.
                payload = {
                    **{k: v for k, v in sidecar.items() if k != "model"},
                    "regenErrors": presented_errors,
                    "session": session_uuid,
                    "project": project_hash,
                    "hasDashboard": has_dashboard,
                    "mtime": jsonl_mtime,
                    "dashboardMtime": dash_mtime,
                    "lastTurnEndedAt": (
                        _LAST_TURN_CACHE.get(jsonl_path)
                        if jsonl_path.exists() else None
                    ),
                    "regen": regen_state,
                    "metrics": metrics,
                }
                body = json.dumps(payload).encode("utf-8")
                etag = f'"{hashlib.md5(body).hexdigest()}"'
                if self.headers.get("If-None-Match") == etag:
                    self.send_response(304)
                    self.send_header("ETag", etag)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                return self._respond(body, "application/json; charset=utf-8",
                                     headers={"ETag": etag})
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

        # /<project-hash>/ → project-index page
        if len(parts) == 1:
            if not (PROJECTS_ROOT / parts[0]).is_dir():
                return self.send_error(404, f"project '{parts[0]}' not found")
            # A member slug (worktree or subdir chat dir) has no index of its
            # own; its sessions are aggregated under the group's front slug.
            gm = project_groups()
            group_key = _group_of_slug(gm, parts[0])
            group = gm["groups"][group_key] if group_key else None
            if group is not None and group["repr"] != parts[0] \
                    and (PROJECTS_ROOT / group["repr"]).is_dir():
                return self._redirect(f"/{group['repr']}/")
            info = parse_project_hash(parts[0])
            if group is None and info["isWorktree"] \
                    and (PROJECTS_ROOT / info["parentHash"]).is_dir():
                return self._redirect(f"/{info['parentHash']}/")
            if not path.endswith("/"):
                return self._redirect(f"/{parts[0]}/")
            label = group["label"] if group is not None else project_label(parts[0])
            root_line = ""
            if group is not None and group["rootPath"]:
                root_line = f"<code>{html.escape(group['rootPath'])}</code><br/>\n    "
            return self._respond(
                render_page("project-index.html",
                            title=f"{label} · chat index",
                            section="projects",
                            breadcrumb=_breadcrumb(("Projects", "/"), (label, None)),
                            page=dict(
                                page_title=f"{label} · chat index",
                                subtitle="All Claude Code sessions in this project · auto-refreshes every 30s",
                                meta_extra=f"{root_line}Project <code>{html.escape(parts[0])}</code><br/>\n    ",
                                footer=f"<code>/api/sessions/{html.escape(parts[0])}.json</code>",
                                strip=True,
                            ),
                            project_hash=parts[0], project_label=label),
                "text/html; charset=utf-8")

        # /<project-hash>/<session-uuid>/dashboard.html
        if (
            len(parts) == 3
            and parts[2] == "dashboard.html"
            and (PROJECTS_ROOT / parts[0]).is_dir()
        ):
            if not _PROJECT_HASH_RE.match(parts[0]) or not _SESSION_UUID_RE.match(parts[1]):
                return self.send_error(400, "invalid project or session id")
            return self._serve_dashboard(parts[0], parts[1])

        # /<project-hash>/<file...> → a static file inside a session dir
        return self._serve_project_static(parts)

    def _send_json(self, payload) -> None:
        self._respond(json.dumps(payload).encode("utf-8"),
                      "application/json; charset=utf-8")

    def _handle_settings_post(self) -> None:
        """Change one setting; config.SCHEMA is the allowlist."""
        data = self._read_json_body()
        if not data or "name" not in data or "value" not in data:
            return self.send_error(400, 'expected {"name": ..., "value": ...}')
        try:
            result = SETTINGS.update(str(data["name"]), data["value"])
        except ValueError as e:
            return self._respond(
                json.dumps({"ok": False, "error": str(e)}).encode("utf-8"),
                "application/json; charset=utf-8", status=400)
        if result["name"] == "CCD_LOG_LEVEL":
            set_log_level(result["value"])
        _log.info("setting changed: %s = %s", result["name"], result["value"])
        return self._send_json({"ok": True, **result})

    def _serve_stats(self) -> None:
        """/api/stats.json?range=1d|7d|30d|all: aggregated regen telemetry."""
        if STORE is None:
            return self._send_json({})
        qs = parse_qs(urlparse(self.path).query)
        rng = (qs.get("range") or ["7d"])[0]
        window, bucket = _STATS_RANGES.get(rng, _STATS_RANGES["7d"])
        since = int(time.time()) - window if window else 0
        timeout_s = SETTINGS.get("CCD_REGEN_TIMEOUT")
        warn_ms = int(timeout_s * 1000 * 2 / 3)
        payload = STORE.stats(since=since, warn_ms=warn_ms, bucket=bucket)
        payload["by_project"] = rebucket_stats_projects(
            payload.get("by_project") or [])
        payload.update({
            "range": rng,
            "since": since,
            "now": int(time.time()),
            "bucket": bucket,
            "timeout_s": round(timeout_s, 1),
            "warn_s": round(timeout_s * 2 / 3, 1),
        })
        self._send_json(payload)

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
        self._respond(body, ct)

    def _serve_project_static(self, parts: "list") -> None:
        """Serve a static file from the projects tree; never a raw .jsonl
        transcript and never a directory listing."""
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

    def _render_dashboard(self, project_hash: str, session_uuid: str, *,
                          title: str, fragment: str) -> bytes:
        """Render a per-chat dashboard (real fragment or pending placeholder)
        through base.html."""
        gm = project_groups()
        group_key = _group_of_slug(gm, project_hash)
        if group_key is not None:
            group = gm["groups"][group_key]
            label, crumb_slug = group["label"], group["repr"]
        else:
            label, crumb_slug = project_label(project_hash), project_hash
        nav_actions = apply_substitutions(
            read_template("_dashboard_actions.html"),
            {"session_uuid": session_uuid, "project_hash": project_hash})
        return render_page(
            "_layout.html",
            title=title, body_class="dashboard", section="projects",
            breadcrumb=_breadcrumb(("Projects", "/"), (label, f"/{crumb_slug}/"),
                                   (title, None)),
            nav_actions=nav_actions,
            # fragment goes LAST: substitutions apply in order, and agent-authored
            # HTML containing a literal {{project_hash}} must survive untouched.
            session_uuid=session_uuid, project_hash=project_hash, fragment=fragment,
        )

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

        # Only a real GET counts as the user opening this dashboard.
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

        title = extract_title(content, session_uuid)
        if title in ("Session", session_uuid):
            # Dashboards rendered before a model title lands carry the generic
            # header; the chat's own title is better for the tab and breadcrumb.
            meta = _META_CACHE.get(PROJECTS_ROOT / project_hash / f"{session_uuid}.jsonl")
            title = meta.get("aiTitle") or title
        body = self._render_dashboard(
            project_hash, session_uuid, title=title, fragment=content)
        mtime = dash_path.stat().st_mtime
        self._respond(body, "text/html; charset=utf-8", headers={
            "Last-Modified": time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(mtime)),
        })

    def _serve_dashboard_placeholder(self, project_hash: str, session_uuid: str) -> None:
        """No dashboard.html yet: serve the _layout shell with the pending
        placeholder, so the status poll surfaces failures and the page
        auto-reloads once a real dashboard lands."""
        body = self._render_dashboard(
            project_hash, session_uuid,
            title="Your live dashboard", fragment=read_template("_pending.html"))
        self._respond(body, "text/html; charset=utf-8")


def main() -> int:
    log_path = configure_logging(RUNTIME_DIR)

    regen_model = SETTINGS.get("CCD_MODEL")
    regen_timeout = SETTINGS.get("CCD_REGEN_TIMEOUT")

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

    def _on_regen_success(project_hash: str, session_uuid: str) -> None:
        STORE.touch_open(project_hash, session_uuid)
        CHAT_STATE.resolve_errors(project_hash, session_uuid)

    REGISTRY = Registry(
        plugin_dir=PLUGIN_DIR,
        projects_root=PROJECTS_ROOT,
        model=regen_model,
        timeout=lambda: SETTINGS.get("CCD_REGEN_TIMEOUT"),
        metrics=STORE,
        on_success=_on_regen_success,
        on_failure=_on_regen_failure,
        chat_state=CHAT_STATE,
    )

    # Daemon thread: server start never blocks on the auth probe.
    def _run_auth_probe() -> None:
        ok, detail = probe_auth()
        AUTH_HEALTH["regenAuth"] = "ok" if ok else "failed"
        AUTH_HEALTH["detail"] = detail
        AUTH_HEALTH["checkedAt"] = int(time.time())
        if ok:
            _log.info("startup auth probe: OK, regen can authenticate")
        else:
            _log.warning(
                "startup auth probe FAILED, new dashboards will NOT generate: %s",
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
    _log.info("  MODEL         = %s  (timeout=%.0fs)", regen_model, regen_timeout)
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

    # The Stop hook runs outside atk's env injection and discovers the bound
    # port through this file.
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
