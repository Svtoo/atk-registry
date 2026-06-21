#!/usr/bin/env python3
"""Plugin manager for claude-dashboard.

Idempotently installs/uninstalls the Stop hook that fires the headless
dashboard updater. The HTTP server's lifecycle is independent — handled
by start.sh/stop.sh and atk start/stop.

Usage:
    manage.py install <plugin_dir>
    manage.py uninstall <plugin_dir>
    manage.py status <plugin_dir>
"""

import json
import shutil
import sys
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"
HOOKS_DIR = CLAUDE_DIR / "hooks"
SETTINGS_PATH = CLAUDE_DIR / "settings.json"

HOOK_SCRIPTS = [
    "dashboard-update-hook.sh",
]

# Stable identifier for OUR hook entry, independent of the exact command string
# (which now bakes in an absolute DASHBOARD_PORT_FILE path so the copied hook can find
# the running server's port). Matching on this substring keeps install/uninstall
# idempotent and lets an upgrade replace an older command form cleanly.
HOOK_COMMAND_MARKER = "dashboard-update-hook.sh"

OWNED_EVENTS = ("Stop",)


def owned_hook_command(plugin_dir: Path) -> str:
    # DASHBOARD_PORT_FILE lets the hook read the server's actual bound port — the hook
    # runs inside Claude Code's process, outside atk's env injection, so it can't
    # otherwise learn a non-default port. bash runs the copy in ~/.claude/hooks/.
    return f"DASHBOARD_PORT_FILE={plugin_dir / 'runtime' / 'port'} bash {HOOKS_DIR}/dashboard-update-hook.sh"


def owned_hooks(plugin_dir: Path) -> dict:
    return {
        event: {
            "hooks": [
                {
                    "type": "command",
                    "command": owned_hook_command(plugin_dir),
                    "timeout": 5,
                }
            ]
        }
        for event in OWNED_EVENTS
    }


def read_settings() -> dict:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        data = json.loads(SETTINGS_PATH.read_text())
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        sys.exit(
            f"ERROR: cannot parse {SETTINGS_PATH}: {e}\n"
            f"  Fix or remove the file, then re-run."
        )
    if not isinstance(data, dict):
        sys.exit(f"ERROR: {SETTINGS_PATH} is not a JSON object; refusing to modify it.")
    return data


def write_settings(data: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.rename(SETTINGS_PATH)


def hook_entry_matches(existing_entry: dict) -> bool:
    """Is this settings entry OUR hook? Matched by the script-name marker so it
    recognises any command form we have shipped (with or without DASHBOARD_PORT_FILE),
    keeping upgrades and uninstall idempotent."""
    for h in existing_entry.get("hooks", []):
        if HOOK_COMMAND_MARKER in (h.get("command") or ""):
            return True
    return False


def install(plugin_dir: Path) -> None:
    print("Installing claude-dashboard hook...")
    hooks_src = plugin_dir / "hooks"

    HOOKS_DIR.mkdir(parents=True, exist_ok=True)
    for script in HOOK_SCRIPTS:
        src = hooks_src / script
        dst = HOOKS_DIR / script
        if not src.exists():
            print(f"  ERROR: missing source hook: {src}")
            sys.exit(1)
        shutil.copy2(src, dst)
        dst.chmod(0o755)
        print(f"  Installed: {script}")

    settings = read_settings()
    hooks = settings.setdefault("hooks", {})

    for event, owned_entry in owned_hooks(plugin_dir).items():
        existing_entries = hooks.get(event, [])
        # Idempotent replace: drop any prior form of our entry, then append the
        # current one.
        filtered = [e for e in existing_entries if not hook_entry_matches(e)]
        filtered.append(owned_entry)
        hooks[event] = filtered
        print(f"  Configured: {event} hook")

    write_settings(settings)

    verify = read_settings()
    for event in OWNED_EVENTS:
        if event not in verify.get("hooks", {}):
            print(f"ERROR: Failed to set {event} hook")
            sys.exit(1)

    print()
    print("claude-dashboard hook installed.")
    print("  Restart Claude Code if you changed the hook *registration* in settings.json.")
    print("  Hook script content changes take effect on the next Stop event automatically.")
    print(f"  Server log: {plugin_dir / 'runtime' / 'server.log'}")


def uninstall(plugin_dir: Path) -> None:
    print("Uninstalling claude-dashboard hook...")

    for script in HOOK_SCRIPTS:
        path = HOOKS_DIR / script
        if path.exists():
            path.unlink()
            print(f"  Removed: {script}")

    if SETTINGS_PATH.exists():
        settings = read_settings()
        hooks = settings.get("hooks", {})

        for event in OWNED_EVENTS:
            existing = hooks.get(event, [])
            filtered = [e for e in existing if not hook_entry_matches(e)]
            if filtered:
                hooks[event] = filtered
            elif event in hooks:
                del hooks[event]
            print(f"  Removed: {event} hook entry")

        if not hooks and "hooks" in settings:
            del settings["hooks"]

        write_settings(settings)

    print()
    print("claude-dashboard hook uninstalled.")


def status(plugin_dir: Path) -> None:
    ok = True

    for script in HOOK_SCRIPTS:
        path = HOOKS_DIR / script
        if not path.exists():
            print(f"MISSING: {path}")
            ok = False

    if SETTINGS_PATH.exists():
        settings = read_settings()
        hooks = settings.get("hooks", {})
        for event in OWNED_EVENTS:
            entries = hooks.get(event, [])
            if not any(hook_entry_matches(e) for e in entries):
                print(f"MISSING: {event} hook")
                ok = False
    else:
        print(f"MISSING: {SETTINGS_PATH}")
        ok = False

    if ok:
        print("OK: claude-dashboard hook is wired")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <install|uninstall|status> <plugin_dir>")
        sys.exit(1)

    action = sys.argv[1]
    plugin_dir = Path(sys.argv[2])

    if action == "install":
        install(plugin_dir)
    elif action == "uninstall":
        uninstall(plugin_dir)
    elif action == "status":
        status(plugin_dir)
    else:
        print(f"Unknown action: {action}")
        sys.exit(1)
