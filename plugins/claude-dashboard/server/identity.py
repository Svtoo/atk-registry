"""Transcript-derived project identity: which real project (git repo or plain
folder) a chat belongs to.

Everything here is pure file reading. Resolving a repo uses the same pointer
files git itself uses (a `.git` directory, or a `.git` file whose single
`gitdir:` line names the main repo) — no subprocess is ever spawned, so
nothing runs on the user's machine beyond stat() and two tiny file reads.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

# The first main-chain cwd sits within the first handful of lines (a few
# cwd-less meta records, then the first user event). 100 lines is far past
# every observed transcript while still bounding a corrupt file.
ANCHOR_SCAN_LINES = 100

CWD_MAX_LEN = 1024

# Shared scratch locations: sessions here are unrelated to each other, so a
# dead directory must never be adopted into a neighbour's project.
TEMP_CONTAINER_PREFIXES = ("/tmp", "/private/tmp", "/var/folders")

_CACHE_TTL_S = 300.0
_cache: "dict[str, tuple[float, dict | None]]" = {}


def session_anchor(jsonl_path: Path, include_sidechain: bool = False) -> dict:
    """First main-chain cwd and gitBranch of a transcript.

    include_sidechain=True accepts sidechain events too — for standalone
    subagent transcripts, whose every event is a sidechain.
    Returns {"cwd": str|None, "gitBranch": str|None}; never raises."""
    cwd = branch = None
    try:
        with jsonl_path.open("r", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i >= ANCHOR_SCAN_LINES:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get("isSidechain") and not include_sidechain:
                    continue
                if cwd is None:
                    c = d.get("cwd")
                    if isinstance(c, str) and c:
                        cwd = c
                if branch is None:
                    b = d.get("gitBranch")
                    if isinstance(b, str) and b:
                        branch = b
                if cwd is not None and branch is not None:
                    break
    except OSError:
        pass
    return {"cwd": cwd, "gitBranch": branch}


def valid_cwd(cwd) -> bool:
    """Transcript data is untrusted: only a sane absolute path may reach
    the filesystem or the UI."""
    if not isinstance(cwd, str) or not cwd.startswith("/"):
        return False
    if len(cwd) > CWD_MAX_LEN:
        return False
    return not any(ord(ch) < 0x20 or ch == "\x7f" for ch in cwd)


def _parse_gitdir_pointer(git_file: Path) -> str | None:
    """The single `gitdir: <path>` line of a worktree's .git file."""
    try:
        text = git_file.read_text(errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("gitdir:"):
            target = line[len("gitdir:"):].strip()
            return target or None
    return None


def resolve_root(cwd: str) -> dict | None:
    """Project root for a live directory, by walking up to the nearest .git.

    Returns {"root", "kind": "repo"|"dir", "isWorktree", "worktreeDir"},
    or None when cwd is invalid or no longer exists."""
    if not valid_cwd(cwd):
        return None
    start = Path(cwd)
    if not start.is_dir():
        return None
    for candidate in (start, *start.parents):
        git = candidate / ".git"
        if git.is_dir():
            return {"root": str(candidate), "kind": "repo",
                    "isWorktree": False, "worktreeDir": None}
        if git.is_file():
            target = _parse_gitdir_pointer(git)
            marker = "/.git/worktrees/"
            if target and marker in target:
                return {"root": target.split(marker, 1)[0], "kind": "repo",
                        "isWorktree": True, "worktreeDir": str(candidate)}
            # Submodule (.git/modules/...) or --separate-git-dir: the
            # checkout is its own project; never guess further.
            return {"root": str(candidate), "kind": "repo",
                    "isWorktree": False, "worktreeDir": None}
    return {"root": cwd, "kind": "dir", "isWorktree": False, "worktreeDir": None}


def resolve_root_cached(cwd: str) -> dict | None:
    now = time.monotonic()
    hit = _cache.get(cwd)
    if hit is not None and now < hit[0]:
        return hit[1]
    value = resolve_root(cwd)
    _cache[cwd] = (now + _CACHE_TTL_S, value)
    return value


def rescue_dead(
    cwd: str,
    live_index: "dict[str, dict | None]",
    home: "str | None" = None,
    temp_prefixes: "tuple[str, ...]" = TEMP_CONTAINER_PREFIXES,
) -> "str | None":
    """Best-effort repo root for a directory that no longer exists
    (a removed worktree, typically). Returns the root, or None when no
    safe answer exists — a wrong standalone card is honest, a wrong
    merge is a lie.

    live_index maps other sessions' live cwds to their resolve_root()."""
    if not valid_cwd(cwd):
        return None
    if home is None:
        home = str(Path.home())
    dead = Path(cwd)

    # A dead path still inside a live repo (e.g. <repo>/.claude/worktrees/x):
    # the nearest surviving ancestor tells us the repo, as long as the repo
    # genuinely contains the dead path and is not just the user's home.
    for anc in dead.parents:
        if anc.is_dir():
            r = resolve_root(str(anc))
            if (r is not None and r["kind"] == "repo"
                    and cwd.startswith(r["root"] + "/")
                    and r["root"] not in (home, "/")):
                return r["root"]
            break

    # Sibling worktrees in the same container dir: adopt their repo only on
    # unambiguous evidence, and never inside shared temp locations. The dead
    # path may be a SUBDIR of the removed worktree, so every dead ancestor
    # level gets a sibling check, down to the first surviving one.
    candidates = [dead]
    for anc in dead.parents:
        if anc.is_dir():
            break
        candidates.append(anc)
    for level in candidates:
        container = level.parent
        c = str(container)
        if c == home or any(c == p or c.startswith(p + "/") for p in temp_prefixes):
            continue
        sibling_roots = set()
        sibling_dirs = set()
        for r in live_index.values():
            if not r or not r["isWorktree"] or not r["worktreeDir"]:
                continue
            if Path(r["worktreeDir"]).parent == container:
                sibling_roots.add(r["root"])
                sibling_dirs.add(r["worktreeDir"])
        if len(sibling_roots) == 1:
            root = next(iter(sibling_roots))
            if container.name == Path(root).name or len(sibling_dirs) >= 2:
                return root
    return None


def slug_for_path(path: str) -> str:
    """The project-dir name Claude Code derives from a cwd."""
    return "".join(ch if ch.isalnum() else "-" for ch in path)
