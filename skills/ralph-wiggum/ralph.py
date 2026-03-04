#!/usr/bin/env python3
"""ralph.py — ATK plugin factory using the Ralph Wiggum loop.

Default (no --role): combined tester-first loop in one thread.
  Each iteration claims a ready_for_testing task first; falls back to pending.
  Use --count N to stop after N tasks (developer + tester combined).

Debug / parallel modes — pass --role to lock the worker to one role:
  --role developer  Only claims 'pending' tasks, builds plugins.
  --role tester     Only claims 'ready_for_testing' tasks, validates plugins.

Usage:
  python ralph.py [--tasks FILE] [--count N]
  python ralph.py --role developer [--tasks FILE] [--count N]
  python ralph.py --role tester   [--tasks FILE] [--count N] [--stale-timeout SECONDS]
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
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import Iterator, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SKILL_DIR = Path(__file__).parent
REGISTRY_ROOT = SKILL_DIR.parent.parent          # atk-registry/
CREATE_PLUGIN_SKILL = SKILL_DIR.parent / "create-atk-plugin" / "SKILL.md"
DEFAULT_TASKS_FILE = REGISTRY_ROOT / "ralph-tasks.yaml"
RALPH_SCRIPT = Path(__file__).resolve()          # used in agent prompts

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TaskStatus(str, Enum):
    PENDING = "pending"
    DEVELOPING = "developing"
    READY_FOR_TESTING = "ready_for_testing"
    TESTING = "testing"
    COMPLETE = "complete"
    FAILED = "failed"
    SKIPPED = "skipped"


class Bug(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    found_in_cycle: int
    severity: Literal["critical", "high", "medium", "low"]
    status: Literal["open", "addressed", "wont_fix"] = "open"
    description: str
    steps_to_reproduce: str
    addressed_in_cycle: int | None = None


class Suggestion(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    cycle: int
    author_role: Literal["developer", "tester"]
    type: Literal["skill_bug", "atk_bug", "process_improvement", "implementation_note"]
    status: str = "open"   # free-form: agents sometimes set custom status values
    description: str
    proposed_fix: str


class TaskFailure(BaseModel):
    timestamp: str
    error: str
    detail: str | None = None


class Task(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    worker_id: str | None = None
    branch: str | None = None
    dev_cycles: int = 0
    started_at: str | None = None
    completed_at: str | None = None
    bugs: list[Bug] = Field(default_factory=list)
    suggestions: list[Suggestion] = Field(default_factory=list)
    failures: list[TaskFailure] = Field(default_factory=list)


class AgentConfig(BaseModel):
    """Configuration for a single role's agent invocation.

    Prompt delivery:
      - instruction_flag set → prompt written to temp file, passed as <flag> <path>
      - instruction_flag None → prompt piped to agent's stdin

    Workspace delivery:
      - workspace_flag set → worktree path appended as <flag> <path>
      - workspace_flag None → agent relies on cwd (suitable for most non-auggie CLIs)
    """

    cmd: str = "auggie"
    flags: list[str] = Field(default_factory=lambda: ["--print"])
    instruction_flag: str | None = "--instruction-file"
    workspace_flag: str | None = "--workspace-root"


class ProcessConfig(BaseModel):
    developer: AgentConfig = Field(default_factory=AgentConfig)
    tester: AgentConfig = Field(default_factory=AgentConfig)
    worktree_base: Path = Path("/tmp/ralph-worktrees")
    branch_prefix: str = "plugin/"
    max_cycles: int = 0  # 0 = unlimited

    @model_validator(mode="before")
    @classmethod
    def _migrate_flat_keys(cls, data: object) -> object:
        """Accept the old flat format (developer_agent, developer_flags, etc.)."""
        if not isinstance(data, dict):
            return data
        for role in ("developer", "tester"):
            agent_key, flags_key = f"{role}_agent", f"{role}_flags"
            if agent_key not in data and flags_key not in data:
                continue
            agent: dict = dict(data.get(role) or {})
            if agent_key in data:
                agent.setdefault("cmd", data.pop(agent_key))
            if flags_key in data:
                raw_flags: list[str] = list(data.pop(flags_key) or [])
                # --workspace-root <value> was a placeholder hack in the old flat format;
                # it is now driven by AgentConfig.workspace_flag — strip it from flags.
                clean: list[str] = []
                i = 0
                while i < len(raw_flags):
                    if raw_flags[i] == "--workspace-root" and i + 1 < len(raw_flags):
                        i += 2
                    else:
                        clean.append(raw_flags[i])
                        i += 1
                agent.setdefault("flags", clean)
            data[role] = agent
        return data


class TasksFile(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: str = "2.0"
    project: str = ""
    description: str = ""
    process: ProcessConfig = Field(default_factory=ProcessConfig)
    tasks: list[Task] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


@contextmanager
def locked_tasks(tasks_file: Path) -> Iterator[TasksFile]:
    """Acquire an exclusive file lock, parse the task file, and save on clean exit."""
    lock_path = tasks_file.with_suffix(".lock")
    with open(lock_path, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            data = TasksFile.model_validate(yaml.safe_load(tasks_file.read_text()) or {})
            yield data
            tasks_file.write_text(
                yaml.dump(
                    data.model_dump(mode="json"),
                    sort_keys=False,
                    allow_unicode=True,
                    default_flow_style=False,
                )
            )
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def _find_task(data: TasksFile, task_id: str) -> Task | None:
    task = next((t for t in data.tasks if t.id == task_id), None)
    if task is None:
        print(f"ERROR: task '{task_id}' not found", file=sys.stderr)
    return task


def _resolve_tasks_file(path_str: str) -> Path | None:
    p = Path(path_str).resolve()
    if not p.exists():
        print(f"ERROR: tasks file not found: {p}", file=sys.stderr)
        return None
    return p


# ---------------------------------------------------------------------------
# Task claiming
# ---------------------------------------------------------------------------

_ROLE_CLAIM: dict[str, tuple[TaskStatus, TaskStatus]] = {
    "developer": (TaskStatus.PENDING, TaskStatus.DEVELOPING),
    "tester":    (TaskStatus.READY_FOR_TESTING, TaskStatus.TESTING),
}

_EXPECTED_STATUSES: dict[str, frozenset[TaskStatus]] = {
    "developer": frozenset({TaskStatus.READY_FOR_TESTING}),
    "tester":    frozenset({TaskStatus.COMPLETE, TaskStatus.PENDING}),
}


def claim_task(
    tasks_file: Path,
    worker_id: str,
    role: str,
    stale_timeout: int | None = None,
) -> Task | None:
    """Atomically claim the next task appropriate for `role`. Returns a snapshot or None.

    If stale_timeout is set, also reclaims tasks stuck in the active state for
    longer than that many seconds — handles crashed agents.
    """
    claimable_status, active_status = _ROLE_CLAIM[role]
    now = _now()

    with locked_tasks(tasks_file) as data:
        for task in data.tasks:
            if task.status == claimable_status:
                task.status = active_status
                task.worker_id = worker_id
                task.started_at = now
                return task.model_copy(deep=True)

            if stale_timeout and task.status == active_status and task.started_at:
                try:
                    started_dt = datetime.datetime.fromisoformat(task.started_at)
                    age = (datetime.datetime.now(datetime.timezone.utc) - started_dt).total_seconds()
                    if age > stale_timeout:
                        print(f"[ralph] reclaiming stale task {task.id} (age={age:.0f}s)")
                        task.status = active_status
                        task.worker_id = worker_id
                        task.started_at = now
                        return task.model_copy(deep=True)
                except ValueError:
                    pass

    return None


# ---------------------------------------------------------------------------
# Git worktree helpers
# ---------------------------------------------------------------------------


def create_worktree(repo_root: Path, branch: str, worktree_dir: Path) -> tuple[bool, str]:
    """Create a git worktree for `branch` at `worktree_dir`.

    If the branch does not exist, creates it from HEAD.
    Returns (success, error_message).
    """
    result = subprocess.run(
        ["git", "worktree", "add", str(worktree_dir), branch],
        capture_output=True, text=True, cwd=repo_root,
    )
    if result.returncode == 0:
        return True, ""

    result = subprocess.run(
        ["git", "worktree", "add", "-b", branch, str(worktree_dir)],
        capture_output=True, text=True, cwd=repo_root,
    )
    if result.returncode == 0:
        return True, ""

    return False, (result.stdout + result.stderr).strip()


def remove_worktree(repo_root: Path, worktree_dir: Path) -> None:
    """Remove a git worktree and prune stale refs. Errors are logged but not raised."""
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree_dir)],
        capture_output=True, cwd=repo_root,
    )
    subprocess.run(["git", "worktree", "prune"], capture_output=True, cwd=repo_root)


# ---------------------------------------------------------------------------
# Prompt construction — one builder per role
# ---------------------------------------------------------------------------


def _suggestion_format(tasks_file: Path, task_id: str, cycle: int, role: str) -> str:
    return (
        "## Suggestions\n"
        "\n"
        "After your work, record each suggestion via the ralph CLI (one command per suggestion):\n"
        "\n"
        f"  uv run {RALPH_SCRIPT} task add-suggestion \\\n"
        f"      --tasks {tasks_file} --id {task_id} \\\n"
        f"      --author-role {role} --cycle {cycle} \\\n"
        "      --type TYPE --description \"DESCRIPTION\" --proposed-fix \"FIX\"\n"
        "\n"
        "TYPE must be one of: skill_bug | atk_bug | process_improvement | implementation_note\n"
        "DESCRIPTION: elaborate and specific. Quote the exact text that was wrong or missing.\n"
        "The CLI validates --type and rejects the command if --proposed-fix is missing.\n"
    )


def _format_open_bugs(bugs: list[Bug], tasks_file: Path, task_id: str, next_cycle: int) -> str:
    open_bugs = [b for b in bugs if b.status == "open"]
    if not open_bugs:
        return ""
    lines = ["## Open Bugs to Fix (from previous testing cycles)", ""]
    for b in open_bugs:
        lines += [
            f"### Bug {b.id} — {b.severity} severity",
            b.description.strip(),
            "",
            "**Steps to reproduce:**",
            b.steps_to_reproduce.strip(),
            "",
            "When fixed, mark it addressed via the ralph CLI:",
            f"  `uv run {RALPH_SCRIPT} task update-bug --tasks {tasks_file} --id {task_id}"
            f" --bug-id {b.id} --status addressed --addressed-in-cycle {next_cycle}`",
            "",
        ]
    return "\n".join(lines)


def _extract_testing_protocol(skill_content: str) -> str:
    """Extract the 'Testing Protocol' section from the create-atk-plugin SKILL.md."""
    marker = "## Testing Protocol"
    idx = skill_content.find(marker)
    if idx == -1:
        return skill_content
    next_section = skill_content.find("\n## ", idx + len(marker))
    return skill_content[idx:next_section] if next_section != -1 else skill_content[idx:]


def build_developer_prompt(task: Task, skill_content: str, tasks_file: Path) -> str:
    current_cycle = task.dev_cycles + 1
    bug_section = _format_open_bugs(task.bugs, tasks_file, task.id, current_cycle)

    sections = [
        "# ATK Plugin Developer",
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
        f"**Task ID**: `{task.id}`  **Plugin name**: `{task.name}`",
        f"**Tasks file**: `{tasks_file}` (use ralph CLI commands — do NOT edit this file directly)",
        "",
        task.description.strip(),
        "",
    ]

    if bug_section:
        sections += [bug_section, ""]

    sections += [
        "---",
        "",
        "## Required Steps (follow in order, do not skip any)",
        "",
        "1. Read the Plugin Creation Skill above in full before writing anything.",
        "2. If open bugs are listed above, read each one and plan your fixes before coding.",
        f"3. Create `plugins/{task.name}/` with `plugin.yaml` and ALL required files.",
        "4. Implement fully — no `echo TODO`, no empty scripts, no stub health checks.",
        "5. `make validate` from the repo root. Fix every error. Repeat until it exits 0.",
        f"6. Self-test: `atk add ./plugins/{task.name}` → status → stop → start"
        f" → `atk mcp show {task.name}` → remove.",
        "7. Address each open bug above. Use the CLI command shown under each bug to mark it addressed.",
        f"8. `git add plugins/{task.name}/ && git commit -m"
        f" 'feat: add {task.name} plugin (cycle {current_cycle})'`",
        "9. Mark the task ready for testing via the ralph CLI:",
        f"   `uv run {RALPH_SCRIPT} task update --tasks {tasks_file} --id {task.id}"
        f" --status ready_for_testing --dev-cycles {current_cycle}`",
        "",
        "DO NOT set ready_for_testing until make validate AND the lifecycle test both pass.",
        "DO NOT write placeholder lifecycle scripts.",
        "",
        _suggestion_format(tasks_file, task.id, current_cycle, "developer"),
    ]
    return "\n".join(sections)


def build_tester_prompt(task: Task, testing_protocol: str, tasks_file: Path) -> str:
    sections = [
        "# ATK Plugin Tester",
        "",
        "You are the TESTER agent. Your job is to FIND what the developer got wrong —",
        "not to confirm it works. Approach this as a QA engineer trying to BREAK the plugin.",
        "",
        "CRITICAL: Do NOT read the plugin implementation code before testing behaviour.",
        "Test the running system against the specification below, not against the code.",
        "",
        "## Task Status Lifecycle (read this — do NOT invent status values)",
        "",
        "You may only set these two statuses:",
        "  - `complete`  — all tests passed, all previously open bugs are fixed",
        "  - `pending`   — sends the task back to the developer with your bug report",
        "",
        "Any other value (e.g. 'failed', 'done', 'pass') is INVALID and will be flagged.",
        "Use the ralph CLI commands below — they validate the status for you.",
        "",
        "---",
        "",
        "## ATK Testing Protocol",
        "",
        testing_protocol,
        "",
        "---",
        "",
        f"## Plugin Specification  (cycle {task.dev_cycles} built by developer)",
        "",
        f"**Task ID**: `{task.id}`  **Plugin name**: `{task.name}`",
        "",
        "What this plugin is supposed to do:",
        "",
        task.description.strip(),
        "",
    ]

    if task.bugs:
        sections += [
            "## Previously Logged Bugs — Verify Each One",
            "",
            "For each open bug below: test it explicitly, then mark it addressed or still-open.",
            "",
        ]
        for b in task.bugs:
            sections += [
                f"Bug {b.id} ({b.status}) — {b.severity}:",
                b.description.strip(),
                "",
                "If now fixed:",
                f"  `uv run {RALPH_SCRIPT} task update-bug --tasks {tasks_file} --id {task.id}"
                f" --bug-id {b.id} --status addressed --addressed-in-cycle {task.dev_cycles}`",
                "",
            ]

    sections += [
        "---",
        "",
        "## Required Steps (follow in order, do not skip any)",
        "",
        f"1. Run the full ATK lifecycle test against `plugins/{task.name}/`:",
        f"   `atk add ./plugins/{task.name}` → `atk status` → `atk stop {task.name}`"
        f" → `atk start {task.name}`",
        f"   → `atk mcp show {task.name}` → `atk uninstall {task.name} --force`"
        f" → `atk install {task.name}` → `atk remove {task.name} --force`",
        "2. Verify every claim in the plugin's README.md.",
        "3. For each previously logged bug above: test it explicitly and mark it using the CLI command shown.",
        "4. Log ALL issues found — even minor ones. Do not filter. Do not assume intent.",
        "   Use the ralph CLI to add each bug (one command per bug):",
        f"   `uv run {RALPH_SCRIPT} task add-bug --tasks {tasks_file} --id {task.id}"
        " --severity SEVERITY --description 'WHAT FAILED' --steps 'EXACT COMMANDS RUN'`",
        "   SEVERITY must be one of: critical | high | medium | low",
        "5. Set the task status via the ralph CLI:",
        "   All tests pass AND all open bugs are fixed:",
        f"     `uv run {RALPH_SCRIPT} task update --tasks {tasks_file} --id {task.id} --status complete`",
        "   Any test fails OR any open bug still reproduces:",
        f"     `uv run {RALPH_SCRIPT} task update --tasks {tasks_file} --id {task.id} --status pending`",
        "",
        "DO NOT set status: complete if any test failed.",
        "DO NOT set status: complete if a previously logged bug is still reproducible.",
        "",
        _suggestion_format(tasks_file, task.id, task.dev_cycles, "tester"),
    ]
    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Agent invocation
# ---------------------------------------------------------------------------


def run_agent(prompt: str, agent: AgentConfig, cwd: Path, task_id: str) -> int:
    """Invoke the agent with the given prompt. Returns the exit code.

    Prompt delivery:
      - instruction_flag set → prompt written to temp file, passed as <flag> <path>
      - instruction_flag None → prompt piped to agent's stdin

    Workspace delivery:
      - workspace_flag set → appended as <flag> <cwd> to the command
      - workspace_flag None → agent relies on subprocess cwd (suitable for most CLIs)
    """
    cmd = [agent.cmd] + list(agent.flags)
    if agent.workspace_flag:
        cmd += [agent.workspace_flag, str(cwd)]

    if agent.instruction_flag:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=f"-ralph-{task_id}.md", delete=False, encoding="utf-8",
        ) as tf:
            tf.write(prompt)
            prompt_file = tf.name
        try:
            cmd += [agent.instruction_flag, prompt_file]
            return subprocess.run(cmd, cwd=cwd).returncode
        finally:
            os.unlink(prompt_file)
    else:
        return subprocess.run(cmd, cwd=cwd, input=prompt, text=True).returncode


def run_validate(repo_root: Path) -> tuple[bool, str]:
    """Run `make validate` at the repo root. Returns (passed, output)."""
    result = subprocess.run(
        ["make", "validate"], capture_output=True, text=True, cwd=repo_root,
    )
    return result.returncode == 0, (result.stdout + result.stderr).strip()


# ---------------------------------------------------------------------------
# Task management CLI — agents call these instead of editing the YAML directly
# ---------------------------------------------------------------------------

_AGENT_STATUSES = {"pending", "ready_for_testing", "complete"}
_SEVERITIES = {"critical", "high", "medium", "low"}
_SUGGESTION_TYPES = {"atk_bug", "implementation_note", "process_improvement", "skill_bug"}


def cmd_task_update(argv: list[str]) -> int:
    """ralph.py task update --tasks FILE --id ID --status STATUS [--dev-cycles N]"""
    parser = argparse.ArgumentParser(prog="ralph.py task update")
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--id", required=True, dest="task_id")
    parser.add_argument("--status", required=True, choices=sorted(_AGENT_STATUSES))
    parser.add_argument("--dev-cycles", type=int, default=None)
    args = parser.parse_args(argv)

    tasks_file = _resolve_tasks_file(args.tasks)
    if tasks_file is None:
        return 1

    with locked_tasks(tasks_file) as data:
        task = _find_task(data, args.task_id)
        if task is None:
            return 1
        task.status = TaskStatus(args.status)
        if args.dev_cycles is not None:
            task.dev_cycles = args.dev_cycles
        if args.status == "complete":
            task.completed_at = _now()

    print(f"OK: task {args.task_id} → status={args.status}")
    return 0


def cmd_task_add_bug(argv: list[str]) -> int:
    """ralph.py task add-bug --tasks FILE --id ID --severity S --description D --steps S"""
    parser = argparse.ArgumentParser(prog="ralph.py task add-bug")
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--id", required=True, dest="task_id")
    parser.add_argument("--severity", required=True, choices=sorted(_SEVERITIES))
    parser.add_argument("--description", required=True)
    parser.add_argument("--steps", required=True)
    args = parser.parse_args(argv)

    tasks_file = _resolve_tasks_file(args.tasks)
    if tasks_file is None:
        return 1

    bug_id = ""
    with locked_tasks(tasks_file) as data:
        task = _find_task(data, args.task_id)
        if task is None:
            return 1
        bug_id = f"b{len(task.bugs) + 1}"
        task.bugs.append(Bug(
            id=bug_id,
            found_in_cycle=task.dev_cycles,
            severity=args.severity,
            status="open",
            description=args.description,
            steps_to_reproduce=args.steps,
        ))

    print(f"OK: bug {bug_id} added to task {args.task_id}")
    return 0


def cmd_task_update_bug(argv: list[str]) -> int:
    """ralph.py task update-bug --tasks FILE --id ID --bug-id BID --status S [--addressed-in-cycle N]"""
    parser = argparse.ArgumentParser(prog="ralph.py task update-bug")
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--id", required=True, dest="task_id")
    parser.add_argument("--bug-id", required=True)
    parser.add_argument("--status", required=True, choices=["open", "addressed", "wont_fix"])
    parser.add_argument("--addressed-in-cycle", type=int, default=None)
    args = parser.parse_args(argv)

    tasks_file = _resolve_tasks_file(args.tasks)
    if tasks_file is None:
        return 1

    with locked_tasks(tasks_file) as data:
        task = _find_task(data, args.task_id)
        if task is None:
            return 1
        bug = next((b for b in task.bugs if b.id == args.bug_id), None)
        if bug is None:
            print(f"ERROR: bug '{args.bug_id}' not found in task {args.task_id}", file=sys.stderr)
            return 1
        bug.status = args.status
        if args.addressed_in_cycle is not None:
            bug.addressed_in_cycle = args.addressed_in_cycle

    print(f"OK: bug {args.bug_id} in task {args.task_id} → status={args.status}")
    return 0


def cmd_task_add_suggestion(argv: list[str]) -> int:
    """ralph.py task add-suggestion --tasks F --id ID --type T --description D --proposed-fix F"""
    parser = argparse.ArgumentParser(prog="ralph.py task add-suggestion")
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--id", required=True, dest="task_id")
    parser.add_argument("--type", required=True, choices=sorted(_SUGGESTION_TYPES), dest="stype")
    parser.add_argument("--description", required=True)
    parser.add_argument("--proposed-fix", required=True)
    parser.add_argument("--author-role", default="developer", choices=["developer", "tester"])
    parser.add_argument("--cycle", type=int, default=None)
    args = parser.parse_args(argv)

    tasks_file = _resolve_tasks_file(args.tasks)
    if tasks_file is None:
        return 1

    sug_id = ""
    with locked_tasks(tasks_file) as data:
        task = _find_task(data, args.task_id)
        if task is None:
            return 1
        sug_id = f"s{len(task.suggestions) + 1}"
        cycle = args.cycle if args.cycle is not None else task.dev_cycles
        task.suggestions.append(Suggestion(
            id=sug_id,
            cycle=cycle,
            author_role=args.author_role,
            type=args.stype,
            description=args.description,
            proposed_fix=args.proposed_fix,
        ))

    print(f"OK: suggestion {sug_id} added to task {args.task_id}")
    return 0


def task_main(argv: list[str]) -> int:
    """Dispatch 'ralph.py task <subcommand>' calls."""
    subcmds: dict[str, object] = {
        "update": cmd_task_update,
        "add-bug": cmd_task_add_bug,
        "update-bug": cmd_task_update_bug,
        "add-suggestion": cmd_task_add_suggestion,
    }
    if not argv or argv[0] not in subcmds:
        print("Usage: ralph.py task <subcommand> [args]", file=sys.stderr)
        print(f"Subcommands: {', '.join(subcmds)}", file=sys.stderr)
        return 1
    return subcmds[argv[0]](argv[1:])  # type: ignore[operator]


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "task":
        return task_main(argv[1:])

    parser = argparse.ArgumentParser(
        description="Parallel ATK plugin factory (developer/tester roles)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--role", default=None, choices=["developer", "tester"],
                        help="Lock to one role (debug/parallel). Omit for combined tester-first loop.")
    parser.add_argument("--tasks", default=str(DEFAULT_TASKS_FILE))
    parser.add_argument("--worker-id", default=None)
    parser.add_argument("--count", type=int, default=None, metavar="N",
                        help="Stop after processing N tasks (across both roles).")
    parser.add_argument("--stale-timeout", type=int, default=None, metavar="SECONDS")
    parser.add_argument("--worktree-base", default=None)
    args = parser.parse_args(argv)

    tasks_file = Path(args.tasks).resolve()
    if not tasks_file.exists():
        print(f"[ralph] ERROR: tasks file not found: {tasks_file}", file=sys.stderr)
        return 1
    if not CREATE_PLUGIN_SKILL.exists():
        print(f"[ralph] ERROR: skill file not found: {CREATE_PLUGIN_SKILL}", file=sys.stderr)
        return 1

    config = TasksFile.model_validate(yaml.safe_load(tasks_file.read_text()) or {}).process
    # When --role is given, lock to that role. Otherwise: tester first, then developer.
    role_order = [args.role] if args.role else ["tester", "developer"]
    worktree_base = Path(args.worktree_base) if args.worktree_base else config.worktree_base
    worker_id = args.worker_id or _worker_id()
    repo_root = tasks_file.parent
    worktree_base.mkdir(parents=True, exist_ok=True)
    skill_content = CREATE_PLUGIN_SKILL.read_text()
    testing_protocol = _extract_testing_protocol(skill_content)

    mode_label = args.role or "auto (tester→developer)"
    count_label = str(args.count) if args.count else "∞"
    print(f"[ralph] mode={mode_label}  worker={worker_id}  count={count_label}")
    print(f"[ralph] tasks={tasks_file}  worktree_base={worktree_base}\n")

    completed = 0
    loop = 0
    while True:
        loop += 1
        print(f"[ralph] ── loop {loop}: scanning for tasks...")

        # Claim the next task — try roles in priority order
        task = None
        role = None
        for r in role_order:
            t = claim_task(tasks_file, worker_id, r, stale_timeout=args.stale_timeout)
            if t is not None:
                task = t
                role = r
                break

        if task is None:
            print(f"[ralph] No claimable tasks — exiting.")
            break

        agent: AgentConfig = getattr(config, role)
        task_name = task.name
        branch = f"{config.branch_prefix}{task_name}"
        worktree_dir = worktree_base / f"{task_name}--{worker_id}"

        # Enforce max_cycles: skip tasks that have exceeded the developer cycle limit
        if role == "developer" and config.max_cycles and task.dev_cycles >= config.max_cycles:
            print(f"[ralph] task {task.id} ({task_name}) has reached max_cycles ({config.max_cycles}) — skipping")
            with locked_tasks(tasks_file) as data:
                t = _find_task(data, task.id)
                if t:
                    t.status = TaskStatus.SKIPPED
            continue

        print(f"[ralph] claimed  role={role}  id={task.id}  name={task_name}  branch={branch}")

        # Set up git worktree — tester checks out the developer's branch
        if worktree_dir.exists():
            remove_worktree(repo_root, worktree_dir)

        checkout_branch = (task.branch or branch) if role == "tester" else branch
        ok, err = create_worktree(repo_root, checkout_branch, worktree_dir)
        if not ok:
            print(f"[ralph] ERROR: could not create worktree: {err}")
            with locked_tasks(tasks_file) as data:
                t = _find_task(data, task.id)
                if t:
                    t.status = TaskStatus.FAILED
                    t.failures.append(TaskFailure(
                        timestamp=_now(), error=f"git worktree creation failed: {err}",
                    ))
            time.sleep(2)
            continue

        # Build role-specific prompt; record branch on developer claim
        if role == "developer":
            prompt = build_developer_prompt(task, skill_content, tasks_file)
            with locked_tasks(tasks_file) as data:
                t = _find_task(data, task.id)
                if t:
                    t.branch = branch
        else:
            prompt = build_tester_prompt(task, testing_protocol, tasks_file)

        # Invoke agent
        print(f"[ralph] invoking {agent.cmd} ({role}) for '{task_name}'...")
        agent_exit = run_agent(prompt, agent, cwd=worktree_dir, task_id=task.id)

        # Developer back-pressure: run make validate after agent finishes
        if role == "developer" and agent_exit == 0:
            valid, validate_output = run_validate(worktree_dir)
            if not valid:
                print(f"[ralph] ✗  make validate FAILED for '{task_name}' — marking failed")
                with locked_tasks(tasks_file) as data:
                    t = _find_task(data, task.id)
                    if t:
                        t.status = TaskStatus.FAILED
                        t.failures.append(TaskFailure(
                            timestamp=_now(),
                            error="make validate failed after agent finished",
                            detail=validate_output[-2000:],
                        ))
                remove_worktree(repo_root, worktree_dir)
                time.sleep(1)
                continue

        # Check outcome by reading the YAML — agent is authoritative on status
        new_status = ""
        try:
            updated = TasksFile.model_validate(yaml.safe_load(tasks_file.read_text()) or {})
            t = next((t for t in updated.tasks if t.id == task.id), None)
            if t:
                new_status = t.status.value
        except Exception as exc:
            print(f"[ralph] WARNING: could not read updated task status: {exc}")

        expected = _EXPECTED_STATUSES[role]
        if agent_exit != 0:
            print(f"[ralph] ✗  agent exited {agent_exit} for '{task_name}'")
            with locked_tasks(tasks_file) as data:
                t = _find_task(data, task.id)
                if t:
                    t.status = TaskStatus.FAILED
                    t.failures.append(TaskFailure(
                        timestamp=_now(), error=f"agent exited {agent_exit}",
                    ))
        elif new_status and TaskStatus(new_status) not in expected:
            expected_str = " | ".join(s.value for s in sorted(expected, key=lambda s: s.value))
            print(f"[ralph] ⚠  agent finished but status is '{new_status}', expected: {expected_str}")
        else:
            print(f"[ralph] ✓  '{task_name}' → {new_status or '(status unchanged)'}")

        remove_worktree(repo_root, worktree_dir)

        completed += 1
        if args.count is not None and completed >= args.count:
            print(f"[ralph] reached --count {args.count} — exiting.")
            break

        time.sleep(1)

    return 0


if __name__ == "__main__":
    sys.exit(main())

