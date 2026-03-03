#!/usr/bin/env python3
"""ralph.py — Parallel ATK plugin factory using the Ralph Wiggum loop.

Two roles, run in parallel, coordinating through ralph-tasks.yaml:
  --role developer  Claims 'pending' tasks, builds plugins, marks ready_for_testing.
  --role tester     Claims 'ready_for_testing' tasks, breaks plugins, marks complete/pending.

Usage:
  python ralph.py --role developer [--tasks FILE] [--worker-id ID] [--once]
  python ralph.py --role tester   [--tasks FILE] [--worker-id ID] [--once]
                                  [--stale-timeout SECONDS]
"""

from __future__ import annotations

import argparse
import datetime
import fcntl
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SKILL_DIR = Path(__file__).parent
REGISTRY_ROOT = SKILL_DIR.parent.parent          # atk-registry/
CREATE_PLUGIN_SKILL = SKILL_DIR.parent / "create-atk-plugin" / "SKILL.md"
DEFAULT_TASKS_FILE = REGISTRY_ROOT / "ralph-tasks.yaml"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text()) or {}


def _save(path: Path, data: dict) -> None:
    path.write_text(
        yaml.dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)
    )


# ---------------------------------------------------------------------------
# Task file operations (all file-locked for concurrent safety)
# ---------------------------------------------------------------------------


def _lock_path(tasks_file: Path) -> Path:
    return tasks_file.with_suffix(".lock")


_ROLE_CLAIM: dict[str, tuple[str, str]] = {
    # role → (statuses_to_claim, status_to_set_when_claimed)
    "developer": ("pending", "developing"),
    "tester":    ("ready_for_testing", "testing"),
}


def claim_task_for_role(
    tasks_file: Path,
    worker_id: str,
    role: str,
    stale_timeout: int | None = None,
) -> dict | None:
    """Atomically claim the next task appropriate for `role`. Returns task dict or None.

    Args:
        tasks_file:     Path to ralph-tasks.yaml.
        worker_id:      Identifier written into the task when claimed.
        role:           'developer' or 'tester'.
        stale_timeout:  If set, also reclaim tasks stuck in the in-progress state
                        (developing / testing) for more than this many seconds —
                        handles crashed agents.
    """
    claimable_status, active_status = _ROLE_CLAIM[role]

    lock = _lock_path(tasks_file)
    with open(lock, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            data = _load(tasks_file)
            now = _now()

            for task in data.get("tasks", []):
                status = task.get("status", "pending")

                # Normal claim
                if status == claimable_status:
                    task["status"] = active_status
                    task["worker_id"] = worker_id
                    task["started_at"] = now
                    _save(tasks_file, data)
                    return dict(task)

                # Stale reclaim: agent crashed mid-session
                if stale_timeout and status == active_status:
                    started = task.get("started_at") or ""
                    if started:
                        try:
                            started_dt = datetime.datetime.fromisoformat(started)
                            age = (datetime.datetime.now(datetime.timezone.utc) - started_dt).total_seconds()
                            if age > stale_timeout:
                                print(f"[ralph] reclaiming stale task {task['id']} (age={age:.0f}s)")
                                task["status"] = active_status
                                task["worker_id"] = worker_id
                                task["started_at"] = now
                                _save(tasks_file, data)
                                return dict(task)
                        except ValueError:
                            pass
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)
    return None


def update_task(tasks_file: Path, task_id: str, **kwargs) -> None:
    """Update arbitrary fields on a task identified by id."""
    lock = _lock_path(tasks_file)
    with open(lock, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            data = _load(tasks_file)
            for task in data.get("tasks", []):
                if task["id"] == task_id:
                    task.update(kwargs)
                    break
            _save(tasks_file, data)
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


# ---------------------------------------------------------------------------
# Prompt construction — one builder per role
# ---------------------------------------------------------------------------

_SUGGESTION_FORMAT = """\
MANDATORY SUGGESTIONS (minimum 3, every cycle, no exceptions):
After your work, append to the suggestions list in ralph-tasks.yaml for task {task_id}:

  suggestions:
    - id: "s<N>"
      cycle: {cycle}
      author_role: {role}
      type: skill_bug | atk_bug | process_improvement | implementation_note
      status: open
      description: |
        [Elaborate, specific. Quote the exact text that was wrong or missing.
         Describe what surprised you, what failed unexpectedly, what the SKILL
         said vs. what actually happened. Be precise — vague descriptions are useless.]
      proposed_fix: |
        [Which file, which section, what to add/change/remove.
         "None" is NOT acceptable. Name the fix even if approximate.]

A suggestion without proposed_fix is incomplete. A cycle with fewer than 3 suggestions
means you stopped looking too early."""


def _format_open_bugs(bugs: list[dict]) -> str:
    open_bugs = [b for b in bugs if b.get("status") == "open"]
    if not open_bugs:
        return ""
    lines = ["## Open Bugs to Fix (from previous testing cycles)", ""]
    for b in open_bugs:
        lines += [
            f"### Bug {b.get('id', '?')} — {b.get('severity', 'unknown')} severity",
            b.get("description", "").strip(),
            "",
            "**Steps to reproduce:**",
            b.get("steps_to_reproduce", "").strip(),
            "",
            f"When fixed, set `status: addressed` and `addressed_in_cycle: {b.get('found_in_cycle', '?') + 1}`",
            "",
        ]
    return "\n".join(lines)


def build_developer_prompt(task: dict, skill_content: str) -> str:
    name = task["name"]
    task_id = task["id"]
    description = task.get("description", "").strip()
    dev_cycles = task.get("dev_cycles", 0)
    current_cycle = dev_cycles + 1

    lines = [
        "# Ralph Wiggum — ATK Plugin Developer",
        "",
        "You are the DEVELOPER agent. Build one ATK registry plugin, self-test it,",
        "commit it, and update the task file. Read the skill carefully — it defines",
        "every requirement. Full implementations only. No stubs, no placeholders.",
        "",
        "---",
        "",
        "## Plugin Creation Skill (read before writing a single file)",
        "",
        skill_content,
        "",
        "---",
        "",
        f"## Your Task  (cycle {current_cycle})",
        "",
        f"**Task ID**: `{task_id}`  **Plugin name**: `{name}`",
        f"**Tasks file**: `ralph-tasks.yaml`",
        "",
        description,
        "",
    ]

    bug_section = _format_open_bugs(task.get("bugs", []))
    if bug_section:
        lines += [bug_section, ""]

    lines += [
        "---",
        "",
        "## Required Steps (follow in order, do not skip any)",
        "",
        "1. Read the Plugin Creation Skill above in full before writing anything.",
        "2. If open bugs are listed above, read each one and plan your fixes before coding.",
        f"3. Create `plugins/{name}/` with `plugin.yaml` and ALL required files.",
        "4. Implement fully — no `echo TODO`, no empty scripts, no stub health checks.",
        "5. `make validate` from the repo root. Fix every error. Repeat until it exits 0.",
        f"6. Self-test: `atk add ./plugins/{name}` → status → stop → start → mcp → remove.",
        "7. Address each open bug above. Set `status: addressed` and `addressed_in_cycle` for each.",
        f"8. `git add plugins/{name}/ && git commit -m 'feat: add {name} plugin (cycle {current_cycle})'`",
        "9. Update `ralph-tasks.yaml` task entry:",
        "   - `status: ready_for_testing`",
        f"  - `dev_cycles: {current_cycle}`",
        "",
        "DO NOT set ready_for_testing until make validate AND the lifecycle test both pass.",
        "DO NOT write placeholder lifecycle scripts.",
        "",
        _SUGGESTION_FORMAT.format(task_id=task_id, cycle=current_cycle, role="developer"),
    ]
    return "\n".join(lines)


def build_tester_prompt(task: dict, testing_protocol: str) -> str:
    name = task["name"]
    task_id = task["id"]
    description = task.get("description", "").strip()
    dev_cycles = task.get("dev_cycles", 0)

    lines = [
        "# Ralph Wiggum — ATK Plugin Tester",
        "",
        "You are the TESTER agent. Your job is to FIND what the developer got wrong —",
        "not to confirm it works. Approach this as a QA engineer trying to BREAK the plugin.",
        "",
        "CRITICAL: Do NOT read the plugin implementation code before testing behaviour.",
        "Test the running system against the specification below, not against the code.",
        "A tester who reports 'all tests passed' in the first cycle is not testing hard enough.",
        "",
        "---",
        "",
        "## ATK Testing Protocol",
        "",
        testing_protocol,
        "",
        "---",
        "",
        f"## Plugin Specification  (cycle {dev_cycles} built by developer)",
        "",
        f"**Task ID**: `{task_id}`  **Plugin name**: `{name}`",
        f"**Tasks file**: `ralph-tasks.yaml`",
        "",
        "What this plugin is supposed to do:",
        "",
        description,
        "",
    ]

    prev_bugs = task.get("bugs", [])
    if prev_bugs:
        lines += [
            "## Previously Logged Bugs — Verify Each One",
            "",
            "For each bug below, explicitly test whether it is now fixed.",
            "Report the result in your bug entries.",
            "",
        ]
        for b in prev_bugs:
            lines += [
                f"Bug {b.get('id', '?')} ({b.get('status', '?')}) — {b.get('severity', '?')}:",
                b.get("description", "").strip(),
                "",
            ]

    lines += [
        "---",
        "",
        "## Required Steps (follow in order, do not skip any)",
        "",
        f"1. Run the full ATK lifecycle test against `plugins/{name}/`:",
        f"   `atk add ./plugins/{name}` → status → stop → start → mcp → uninstall → install → remove`",
        "2. Verify every claim in the plugin's README.md.",
        "3. For each previously logged bug above: test it explicitly and record your finding.",
        "4. Log ALL issues found — even minor ones. Do not filter. Do not assume intent.",
        "5. Update `ralph-tasks.yaml` task entry:",
        "   - If ALL tests pass AND all previously open bugs are fixed: `status: complete`",
        "   - If ANY test fails OR any bug still reproduces: `status: pending`",
        "   - Add each issue as a structured entry in `bugs[]` (see YAML schema in ralph-tasks.yaml)",
        "",
        "DO NOT set status: complete if any test failed.",
        "DO NOT set status: complete if a previously logged bug is still reproducible.",
        "",
        _SUGGESTION_FORMAT.format(task_id=task_id, cycle=dev_cycles, role="tester"),
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Agent invocation + validation
# ---------------------------------------------------------------------------


def run_agent(
    prompt: str,
    agent_cmd: str,
    agent_flags: list[str],
    cwd: Path,
    workspace_root: Path,
    task_id: str,
) -> tuple[int, str]:
    """Write prompt to a temp file and invoke the agent via --instruction-file.

    Using --instruction-file instead of stdin because:
    - auggie uses --instruction-file for non-interactive one-shot operation
    - avoids shell quoting issues with long prompts
    - temp file is cleaned up after the agent exits
    """
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=f"-ralph-{task_id}.md",
        delete=False,
        encoding="utf-8",
    ) as tf:
        tf.write(prompt)
        prompt_file = tf.name

    try:
        # --workspace-root is mandatory for auggie to index the right repo.
        # We inject it here so the task file only needs the other flags.
        extra: list[str] = []
        if "--workspace-root" not in agent_flags:
            extra = ["--workspace-root", str(workspace_root)]

        cmd = [agent_cmd] + agent_flags + extra + ["--instruction-file", prompt_file]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
        return result.returncode, (result.stdout + result.stderr)
    finally:
        os.unlink(prompt_file)


def run_validate(repo_root: Path) -> tuple[bool, str]:
    """Run `make validate` at the repo root. Returns (passed, output)."""
    result = subprocess.run(
        ["make", "validate"],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    return result.returncode == 0, (result.stdout + result.stderr).strip()


def _extract_testing_protocol(skill_content: str) -> str:
    """Extract the 'Testing Protocol' section from the create-atk-plugin SKILL.md."""
    marker = "## Testing Protocol"
    idx = skill_content.find(marker)
    if idx == -1:
        return skill_content   # fall back to full content if section not found
    # end at the next top-level ## section
    next_section = skill_content.find("\n## ", idx + len(marker))
    return skill_content[idx:next_section] if next_section != -1 else skill_content[idx:]


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:  # noqa: C901
    parser = argparse.ArgumentParser(
        description="Ralph Wiggum — Parallel ATK plugin factory (developer/tester roles)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--role",
        required=True,
        choices=["developer", "tester"],
        help="Role this worker plays: 'developer' builds, 'tester' breaks",
    )
    parser.add_argument(
        "--tasks",
        default=str(DEFAULT_TASKS_FILE),
        help="Path to ralph-tasks.yaml",
    )
    parser.add_argument(
        "--worker-id",
        default=None,
        help="Worker identifier (default: hostname-pid)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process exactly one task and exit",
    )
    parser.add_argument(
        "--stale-timeout",
        type=int,
        default=None,
        metavar="SECONDS",
        help="Reclaim tasks stuck in developing/testing for longer than this many seconds",
    )
    parser.add_argument(
        "--worktree-base",
        default="/tmp/ralph-worktrees",
        help="Base directory for git worktrees (default: /tmp/ralph-worktrees)",
    )
    args = parser.parse_args(argv)

    tasks_file = Path(args.tasks).resolve()
    if not tasks_file.exists():
        print(f"[ralph] ERROR: tasks file not found: {tasks_file}", file=sys.stderr)
        return 1

    if not CREATE_PLUGIN_SKILL.exists():
        print(f"[ralph] ERROR: skill file not found: {CREATE_PLUGIN_SKILL}", file=sys.stderr)
        return 1

    # Load process config from task file (agent cmd + flags)
    tasks_data = _load(tasks_file)
    process_cfg = tasks_data.get("process", {})
    role = args.role
    agent_cmd = process_cfg.get(f"{role}_agent", "auggie")
    agent_flags: list[str] = process_cfg.get(f"{role}_flags", ["--print"])

    worker_id = args.worker_id or _worker_id()
    repo_root = tasks_file.parent
    worktree_base = Path(args.worktree_base)
    worktree_base.mkdir(parents=True, exist_ok=True)
    skill_content = CREATE_PLUGIN_SKILL.read_text()
    testing_protocol = _extract_testing_protocol(skill_content)

    print(f"[ralph] role={role}  worker={worker_id}  agent={agent_cmd}")
    print(f"[ralph] tasks={tasks_file}  worktree_base={worktree_base}\n")

    loop = 0
    while True:
        loop += 1
        print(f"[ralph] ── loop {loop} ({role}): scanning for tasks...")

        task = claim_task_for_role(tasks_file, worker_id, role, stale_timeout=args.stale_timeout)
        if task is None:
            print(f"[ralph] No claimable tasks for role '{role}' — exiting.")
            break

        task_id: str = task["id"]
        task_name: str = task["name"]
        branch = f"plugin/{task_name}"
        worktree_dir = worktree_base / f"{task_name}--{worker_id}"

        print(f"[ralph] claimed  id={task_id}  name={task_name}  branch={branch}")

        # ── Set up git worktree ──────────────────────────────────────────────
        if worktree_dir.exists():
            remove_worktree(repo_root, worktree_dir)

        if role == "developer":
            # Developer creates a new branch for this plugin
            ok, err = create_worktree(repo_root, branch, worktree_dir)
        else:
            # Tester checks out the existing branch the developer committed to
            existing_branch = task.get("branch") or branch
            ok, err = create_worktree(repo_root, existing_branch, worktree_dir)

        if not ok:
            print(f"[ralph] ERROR: could not create worktree: {err}")
            update_task(tasks_file, task_id, status="failed",
                        failures=(task.get("failures") or []) + [{
                            "timestamp": _now(),
                            "error": f"git worktree creation failed: {err}",
                        }])
            if args.once:
                break
            time.sleep(2)
            continue

        # ── Build role-appropriate prompt ────────────────────────────────────
        if role == "developer":
            prompt = build_developer_prompt(task, skill_content)
            update_task(tasks_file, task_id, branch=branch)
        else:
            prompt = build_tester_prompt(task, testing_protocol)

        # ── Invoke agent ─────────────────────────────────────────────────────
        print(f"[ralph] invoking {agent_cmd} ({role}) for '{task_name}'...")
        agent_exit, agent_output = run_agent(
            prompt, agent_cmd, agent_flags,
            cwd=worktree_dir,
            workspace_root=repo_root,
            task_id=task_id,
        )

        # ── Developer: also run make validate as back-pressure ───────────────
        if role == "developer" and agent_exit == 0:
            valid, validate_output = run_validate(worktree_dir)
            if not valid:
                print(f"[ralph] ✗  make validate FAILED for '{task_name}' — marking failed")
                update_task(tasks_file, task_id, status="failed",
                            failures=(task.get("failures") or []) + [{
                                "timestamp": _now(),
                                "error": "make validate failed after agent finished",
                                "detail": validate_output[-2000:],
                            }])
                remove_worktree(repo_root, worktree_dir)
                if args.once:
                    break
                time.sleep(1)
                continue

        # ── Check outcome by reading the YAML (agent is authoritative) ───────
        updated_task = {}
        try:
            updated_data = _load(tasks_file)
            for t in updated_data.get("tasks", []):
                if t["id"] == task_id:
                    updated_task = t
                    break
        except Exception:
            pass

        new_status = updated_task.get("status", "")
        expected = {"developer": "ready_for_testing", "tester": {"complete", "pending"}}[role]

        if agent_exit != 0:
            print(f"[ralph] ✗  agent exited {agent_exit} for '{task_name}'")
            update_task(tasks_file, task_id, status="failed",
                        failures=(task.get("failures") or []) + [{
                            "timestamp": _now(),
                            "error": f"agent exited {agent_exit}",
                        }])
        elif isinstance(expected, set) and new_status not in expected:
            print(f"[ralph] ⚠  agent finished but status is '{new_status}', expected one of {expected}")
        elif isinstance(expected, str) and new_status != expected:
            print(f"[ralph] ⚠  agent finished but status is '{new_status}', expected '{expected}'")
        else:
            print(f"[ralph] ✓  '{task_name}' → {new_status}")

        # ── Clean up worktree ────────────────────────────────────────────────
        remove_worktree(repo_root, worktree_dir)

        if args.once:
            break

        time.sleep(1)

    return 0


if __name__ == "__main__":
    sys.exit(main())

