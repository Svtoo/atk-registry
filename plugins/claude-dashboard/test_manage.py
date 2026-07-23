#!/usr/bin/env python3
"""Tests for manage.py hook wiring: the SessionStart->UserPromptSubmit
migration, coexistence with other plugins' hook entries, and idempotency.

Sandboxed — points manage at a temp settings.json + temp hooks dir, so it never
touches the real ~/.claude. Run: python3 test_manage.py
"""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "server"))
import manage  # noqa: E402
from testutil import run_module_tests  # noqa: E402

# Stand-ins for OTHER plugins' hook entries that must never be disturbed.
NOTIFY = {"hooks": [{"type": "command", "command": "bash /x/notification-tts.sh", "timeout": 15}]}
ATK_UPS = {"hooks": [{"type": "command", "command": "bash /x/claude-code-atk-reminder.sh", "timeout": 5}]}


def _seed_old_layout() -> dict:
    """settings.json as it looked under the OLD layout: our open hook on
    SessionStart, our regen hook on Stop, plus unrelated plugins' entries."""
    return {
        "hooks": {
            "Stop": [NOTIFY, {"hooks": [{"type": "command",
                "command": "DASHBOARD_PORT_FILE=/p/runtime/port bash /h/dashboard-update-hook.sh",
                "timeout": 5}]}],
            "PermissionRequest": [NOTIFY],
            "UserPromptSubmit": [ATK_UPS],
            "SessionStart": [{"hooks": [{"type": "command",
                "command": "DASHBOARD_PLUGIN_DIR=/p bash /h/dashboard-open-hook.sh",
                "timeout": 5}]}],
        }
    }


def _setup(tmp: str) -> Path:
    settings = Path(tmp) / "settings.json"
    manage.SETTINGS_PATH = settings
    manage.HOOKS_DIR = Path(tmp) / "hooks"
    return settings


def _commands(entries) -> list:
    return [h.get("command", "") for e in entries for h in e.get("hooks", [])]


def test_install_migrates_sessionstart_to_userpromptsubmit():
    with tempfile.TemporaryDirectory() as tmp:
        settings = _setup(tmp)
        settings.write_text(json.dumps(_seed_old_layout()))
        manage.install(HERE)
        hooks = json.loads(settings.read_text())["hooks"]
        # stale SessionStart entry removed (ours was the only one there)
        assert "SessionStart" not in hooks, hooks.get("SessionStart")
        # our open hook now on UserPromptSubmit, coexisting with the atk reminder
        ups = _commands(hooks["UserPromptSubmit"])
        assert any("dashboard-open-hook.sh" in c for c in ups), ups
        assert any("claude-code-atk-reminder.sh" in c for c in ups), ups
        # our regen hook still on Stop, coexisting with notification-tts
        stop = _commands(hooks["Stop"])
        assert any("dashboard-update-hook.sh" in c for c in stop), stop
        assert any("notification-tts.sh" in c for c in stop), stop
        # an unrelated event is untouched
        assert _commands(hooks["PermissionRequest"]) == ["bash /x/notification-tts.sh"]


def test_install_is_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        settings = _setup(tmp)
        settings.write_text(json.dumps(_seed_old_layout()))
        manage.install(HERE)
        once = settings.read_text()
        manage.install(HERE)
        twice = settings.read_text()
        assert once == twice
        ups = _commands(json.loads(twice)["hooks"]["UserPromptSubmit"])
        assert sum("dashboard-open-hook.sh" in c for c in ups) == 1, ups


def test_uninstall_removes_ours_keeps_others():
    with tempfile.TemporaryDirectory() as tmp:
        settings = _setup(tmp)
        settings.write_text(json.dumps(_seed_old_layout()))
        manage.install(HERE)
        manage.uninstall(HERE)
        hooks = json.loads(settings.read_text()).get("hooks", {})
        all_cmds = [c for ev in hooks.values() for c in _commands(ev)]
        # ours gone everywhere (incl. the legacy SessionStart slot)
        assert not any("dashboard-open-hook.sh" in c for c in all_cmds), all_cmds
        assert not any("dashboard-update-hook.sh" in c for c in all_cmds), all_cmds
        # other plugins' entries preserved
        assert any("notification-tts.sh" in c for c in all_cmds), all_cmds
        assert any("claude-code-atk-reminder.sh" in c for c in all_cmds), all_cmds


if __name__ == "__main__":
    run_module_tests(globals())
