#!/usr/bin/env python3
"""UserPromptSubmit hook logic for claude-dashboard: once per session, tell the
agent to open this chat's dashboard URL in the Claude Code Browser pane.
Only the agent can open the pane, so the instruction goes to it."""
import json
import os
import re
import sys
from pathlib import Path

DEFAULT_PORT = 7878

# Session ids are UUIDs, but sanitise before using one as a marker filename.
_UNSAFE_FILENAME_RE = re.compile(r"[^0-9A-Za-z_-]")

# Opt-out switch (plugin.yaml). A Claude Code hook doesn't get atk's .env
# injection, so read the env first, then the plugin's .env file.
PREVIEW_FLAG = "CCD_PREVIEW_PANE"
_DISABLE_VALUES = {"0", "false", "no", "off", "disable", "disabled"}


def _read_config(plugin_dir: Path, key: str) -> "str | None":
    val = os.environ.get(key)
    if val is not None:
        return val
    try:
        for line in (plugin_dir / ".env").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == key:
                return v.strip().strip('"').strip("'")
    except (OSError, ValueError):
        pass
    return None


def preview_enabled(plugin_dir: Path) -> bool:
    """Whether the Browser-pane integration is on (default true)."""
    val = _read_config(plugin_dir, PREVIEW_FLAG)
    if val is None:
        return True
    return val.strip().lower() not in _DISABLE_VALUES


def server_port(plugin_dir: Path) -> int:
    """The dashboard server's bound port from runtime/port; DEFAULT_PORT if unread."""
    try:
        return int((plugin_dir / "runtime" / "port").read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return DEFAULT_PORT


def load_payload() -> dict:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def dashboard_url(transcript_path: str, plugin_dir: Path) -> "str | None":
    """This chat's dashboard URL on the one atk-owned server, or None."""
    if not transcript_path:
        return None
    p = Path(transcript_path)
    proj_hash = p.parent.name
    session = p.stem
    if not proj_hash or not session:
        return None
    return f"http://localhost:{server_port(plugin_dir)}/{proj_hash}/{session}/dashboard.html"


def open_instruction(url: str) -> str:
    """The <system-reminder> telling the agent to open (and, on request, reopen)
    this chat's dashboard URL. Names the tool by argument, not an MCP server."""
    return (
        "<system-reminder>\n"
        "HIGHEST PRIORITY — claude-dashboard live Browser pane.\n\n"
        "This chat has a live executive dashboard at:\n"
        "  " + url + "\n\n"
        "Surface it in the Code Browser pane NOW, in parallel with your first "
        'action this turn: call the `preview_start` tool with {"url": "' + url + '"}. '
        "One call opens the pane directly on this chat's dashboard on the local "
        "server.\n\n"
        "This URL is stable for this chat. If the pane is later closed or lost, or "
        "the user asks you to open or reopen the dashboard, open this same URL the "
        "same way — you always have it here.\n\n"
        "If you already opened the pane for this chat earlier this session, do "
        "nothing now. If no preview/Browser-pane tool is available (e.g. a plain "
        "CLI), skip silently. Do not skip just because the user's request seems "
        "unrelated — it is one fast call and the user relies on the pane.\n"
        "</system-reminder>"
    )


def opened_marker(plugin_dir: Path, session_id: str) -> Path:
    """Per-session marker so the open instruction injects once, not every turn."""
    safe = _UNSAFE_FILENAME_RE.sub("", session_id)
    return plugin_dir / "runtime" / "opened" / safe


def main() -> None:
    plugin_dir = os.environ.get("DASHBOARD_PLUGIN_DIR")
    if not plugin_dir:
        return
    plugin_dir = Path(plugin_dir)
    if not preview_enabled(plugin_dir):
        return
    payload = load_payload()
    if payload.get("hook_event_name") != "UserPromptSubmit":
        return

    transcript = payload.get("transcript_path", "")
    session_uuid = payload.get("session_id") or (Path(transcript).stem if transcript else "")
    url = dashboard_url(transcript, plugin_dir)
    if not url or not session_uuid:
        return

    marker = opened_marker(plugin_dir, session_uuid)
    if marker.exists():
        return

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": open_instruction(url),
        }
    }))

    # Mark after emitting, so a failed marker write re-injects next turn rather
    # than dropping the open.
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("")
    except OSError:
        pass


if __name__ == "__main__":
    main()
