#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook for claude-dashboard.

Runs preview/session_open.py, which injects the once-per-session Browser-pane
open instruction.

The plugin dir arrives as argv[1] rather than as a `VAR=value cmd` environment
prefix: that prefix is POSIX-shell syntax, and Claude Code runs hook commands
through the platform shell, so on Windows it fails to parse.

session_open.py is executed in-process (runpy) rather than spawned, so it
inherits this process's stdin, which carries the hook payload.

Usage (baked into the hook command by manage.py):
    dashboard-open-hook.py <plugin_dir>
"""
import os
import runpy
import sys
from pathlib import Path


def main() -> None:
    # Short-circuit inside our own headless subagent (it also runs with
    # --setting-sources local, which skips user hooks).
    if os.environ.get("CLAUDE_DASHBOARD_SUBAGENT"):
        return

    plugin_dir = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DASHBOARD_PLUGIN_DIR", "")
    if not plugin_dir:
        return

    target = Path(plugin_dir) / "preview" / "session_open.py"
    if not target.exists():
        return

    # session_open.py reads the plugin dir from the environment.
    os.environ["DASHBOARD_PLUGIN_DIR"] = str(plugin_dir)
    runpy.run_path(str(target), run_name="__main__")


if __name__ == "__main__":
    main()
    sys.exit(0)
