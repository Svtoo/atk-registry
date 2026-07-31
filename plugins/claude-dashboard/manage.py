#!/usr/bin/env python3
"""Plugin manager for claude-dashboard.

Idempotently installs/uninstalls the plugin's Claude Code hooks: a Stop hook
(fires the headless dashboard regen) and a UserPromptSubmit hook (injects the
once-per-session Browser-pane open instruction), and strips any stale
SessionStart hook entry. The HTTP server's lifecycle is separate (start.sh /
stop.sh / atk start/stop).

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
    "dashboard-update-hook.py",
    "dashboard-open-hook.py",
]

# The bash wrappers these replaced. Removed on install so upgrading from the
# older layout doesn't leave a dead script and a stale registration behind.
LEGACY_HOOK_SCRIPTS = [
    "dashboard-update-hook.sh",
    "dashboard-open-hook.sh",
]

# Our hook entries are matched by the script name in their command (independent
# of the exact command string, which bakes in absolute paths). Matching on these
# keeps install/uninstall idempotent and lets an upgrade replace an older form.
HOOK_COMMAND_MARKERS = tuple(HOOK_SCRIPTS) + tuple(LEGACY_HOOK_SCRIPTS)

# event -> the hook script that owns it. Stop fires the regen; UserPromptSubmit
# injects the once-per-session Browser-pane open instruction. UserPromptSubmit
# (not SessionStart) because SessionStart additionalContext suppresses Claude
# Code's chat-title generation.
OWNED_EVENTS = ("Stop", "UserPromptSubmit")

# install()/uninstall() also strip our entries from these events (an older
# layout registered the open hook on SessionStart).
LEGACY_EVENTS = ("SessionStart",)


def venv_python(plugin_dir: Path) -> Path:
    """The plugin's pinned interpreter, which install.sh created."""
    scripts = plugin_dir / ".venv" / "Scripts" / "python.exe"  # Windows layout
    return scripts if scripts.exists() else plugin_dir / ".venv" / "bin" / "python"


def owned_hook_command(event: str, plugin_dir: Path) -> str:
    # Absolute paths are baked in because the copied hook runs inside Claude
    # Code's process, outside atk's env injection, so it cannot otherwise find
    # the plugin or the server's bound port.
    #
    # Values are passed as argv rather than as a `VAR=value cmd` prefix: that
    # prefix is POSIX-shell syntax, and Claude Code runs hook commands through
    # the platform shell, so it fails to parse on Windows. Invoking the plugin's
    # own interpreter also drops the dependency on `bash` being on PATH.
    py = venv_python(plugin_dir)
    if event == "Stop":
        # argv[1] lets the regen hook read the server's actual port.
        port_file = plugin_dir / "runtime" / "port"
        return f'"{py}" "{HOOKS_DIR / "dashboard-update-hook.py"}" "{port_file}"'
    if event == "UserPromptSubmit":
        # argv[1] lets the open hook find preview/session_open.py.
        return f'"{py}" "{HOOKS_DIR / "dashboard-open-hook.py"}" "{plugin_dir}"'
    raise ValueError(f"no hook command defined for event {event!r}")


def owned_hooks(plugin_dir: Path) -> dict:
    return {
        event: {
            "hooks": [
                {
                    "type": "command",
                    "command": owned_hook_command(event, plugin_dir),
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
    # replace(), not rename(): both overwrite an existing target on POSIX, but
    # the Windows os.rename underneath raises FileExistsError instead.
    tmp.replace(SETTINGS_PATH)


def hook_entry_matches(existing_entry: dict) -> bool:
    """Is this settings entry OUR hook? Matched by hook-script name so it
    recognises any command form we have shipped, keeping upgrades and uninstall
    idempotent."""
    for h in existing_entry.get("hooks", []):
        command = h.get("command") or ""
        if any(marker in command for marker in HOOK_COMMAND_MARKERS):
            return True
    return False


def install(plugin_dir: Path) -> None:
    print("Installing claude-dashboard hook...")
    hooks_src = plugin_dir / "hooks"

    HOOKS_DIR.mkdir(parents=True, exist_ok=True)

    for stale in LEGACY_HOOK_SCRIPTS:
        path = HOOKS_DIR / stale
        if path.exists():
            path.unlink()
            print(f"  Removed legacy hook: {stale}")

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

    # Drop our entries from LEGACY_EVENTS.
    for event in LEGACY_EVENTS:
        existing_entries = hooks.get(event, [])
        filtered = [e for e in existing_entries if not hook_entry_matches(e)]
        if len(filtered) != len(existing_entries):
            print(f"  Removed stale {event} hook entry")
        if filtered:
            hooks[event] = filtered
        elif event in hooks:
            del hooks[event]

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

    for script in (*HOOK_SCRIPTS, *LEGACY_HOOK_SCRIPTS):
        path = HOOKS_DIR / script
        if path.exists():
            path.unlink()
            print(f"  Removed: {script}")

    if SETTINGS_PATH.exists():
        settings = read_settings()
        hooks = settings.get("hooks", {})

        for event in (*OWNED_EVENTS, *LEGACY_EVENTS):
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
