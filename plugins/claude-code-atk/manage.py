#!/usr/bin/env python3
"""claude-code-atk: install / uninstall / status.

Idempotently patches ~/.claude/settings.json with the UserPromptSubmit hook
that reminds Claude to follow each plugged ATK SKILL.md before answering.

Every operation is keyed on the hook command string so this plugin only ever
touches entries it owns — coexisting plugins that wire their own hooks on
the same event are preserved untouched.
"""

import json
import os
import shutil
import sys
from pathlib import Path

CLAUDE_DIR = Path(os.environ.get("CLAUDE_DIR", Path.home() / ".claude"))
HOOKS_DIR = CLAUDE_DIR / "hooks"
SETTINGS_PATH = CLAUDE_DIR / "settings.json"

HOOK_SCRIPTS = ["claude-code-atk-reminder.sh"]

OWNED_HOOKS = {
    "UserPromptSubmit": {
        "hooks": [
            {
                "type": "command",
                "command": f"bash {HOOKS_DIR}/claude-code-atk-reminder.sh",
                "timeout": 5,
            }
        ]
    },
}


def read_settings() -> dict:
    if SETTINGS_PATH.exists():
        return json.loads(SETTINGS_PATH.read_text())
    return {}


def write_settings(data: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.rename(SETTINGS_PATH)


def hook_entry_matches(existing_entry: dict, owned_entry: dict) -> bool:
    """True if existing entry's first hook command equals the owned entry's."""
    existing_hooks = existing_entry.get("hooks", [])
    owned_hooks = owned_entry.get("hooks", [])
    if not existing_hooks or not owned_hooks:
        return False
    return existing_hooks[0].get("command") == owned_hooks[0].get("command")


def install(plugin_dir: Path) -> None:
    print("Installing claude-code-atk...")
    hooks_src = plugin_dir / "hooks"

    HOOKS_DIR.mkdir(parents=True, exist_ok=True)
    for script in HOOK_SCRIPTS:
        src = hooks_src / script
        dst = HOOKS_DIR / script
        if not src.exists():
            print(f"  ERROR: source hook missing: {src}")
            sys.exit(1)
        shutil.copy2(src, dst)
        dst.chmod(0o755)
        print(f"  Installed: {script}")

    settings = read_settings()
    hooks = settings.setdefault("hooks", {})

    for event, owned_entry in OWNED_HOOKS.items():
        existing = hooks.get(event, [])
        filtered = [e for e in existing if not hook_entry_matches(e, owned_entry)]
        filtered.append(owned_entry)
        hooks[event] = filtered
        print(f"  Configured: {event} hook")

    write_settings(settings)

    verify = read_settings()
    for event, owned_entry in OWNED_HOOKS.items():
        entries = verify.get("hooks", {}).get(event, [])
        if not any(hook_entry_matches(e, owned_entry) for e in entries):
            print(f"ERROR: {event} hook not present after install")
            sys.exit(1)

    print()
    print("claude-code-atk installed.")
    print("  Restart Claude Code to activate.")


def uninstall(plugin_dir: Path) -> None:
    print("Uninstalling claude-code-atk...")

    for script in HOOK_SCRIPTS:
        path = HOOKS_DIR / script
        if path.exists():
            path.unlink()
            print(f"  Removed: {script}")

    if not SETTINGS_PATH.exists():
        print("  No settings.json — nothing to unpatch.")
        return

    settings = read_settings()
    hooks = settings.get("hooks", {})

    for event, owned_entry in OWNED_HOOKS.items():
        if event not in hooks:
            continue
        filtered = [e for e in hooks[event] if not hook_entry_matches(e, owned_entry)]
        if filtered:
            hooks[event] = filtered
        else:
            del hooks[event]
        print(f"  Removed: {event} entry")

    if "hooks" in settings and not settings["hooks"]:
        del settings["hooks"]

    write_settings(settings)
    print()
    print("claude-code-atk uninstalled.")


def status(plugin_dir: Path) -> None:
    ok = True

    for script in HOOK_SCRIPTS:
        path = HOOKS_DIR / script
        if not path.exists():
            print(f"MISSING: {path}")
            ok = False

    if not SETTINGS_PATH.exists():
        print(f"MISSING: {SETTINGS_PATH}")
        sys.exit(1)

    settings = read_settings()
    hooks = settings.get("hooks", {})
    for event, owned_entry in OWNED_HOOKS.items():
        entries = hooks.get(event, [])
        if not any(hook_entry_matches(e, owned_entry) for e in entries):
            print(f"MISSING: {event} hook entry")
            ok = False

    if ok:
        print("claude-code-atk is installed and wired into Claude Code settings.")
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
