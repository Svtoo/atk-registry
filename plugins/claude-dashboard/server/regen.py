"""
Per-session dashboard regeneration: job registry + claude-p runner.

A "regen job" is a `claude -p` subprocess that reads the recent transcript
for one Claude Code session, asks Sonnet to update the dashboard fragment,
and atomically writes the result. The Registry owns at most one in-flight
job per session_uuid: a new trigger while one is in flight coalesces into a
single follow-up (superseding only a wedged, stale job; see Registry.trigger).
Execution state lives in process memory, so the server can expose it cleanly
to the index UI.

Layered responsibilities:
  - transcript curation    pure functions over the JSONL (split_into_turns,
                           select_turns_within_word_budget, render_curated_events)
  - `invoke_claude()`      runs the subprocess; the caller wires up Popen
                           so the Registry can SIGTERM on supersede
  - `run_once()`           one full regen attempt (curate, invoke, write)
  - `Registry`             schedules run_once on a daemon thread, tracks
                           state, coalesces triggers, surfaces state for the API
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from logging_config import get_logger

_log = get_logger("regen")

# ─── Constants ─────────────────────────────────────────────────────────

DEFAULT_MODEL = "sonnet"
DEFAULT_N_TURNS = 6

# Wall-clock ceiling for one `claude -p` regeneration. The dashboard is only
# useful if it tracks the chat closely, so a regen that runs much longer than a
# turn is worthless; we kill it rather than let it wedge the worker forever.
# Override with CCD_REGEN_TIMEOUT.
DEFAULT_REGEN_TIMEOUT = 180.0

# Word budget for the recent-transcript portion of the regen prompt. Recency
# beats history: whole turns are included newest-first up to this many words, and
# the MOST RECENT turn is always included in FULL (every tool call, never
# truncated) even if it alone exceeds the budget; older turns that don't fit are
# dropped with a marker. WORDS (not characters) because the model reasons in
# tokens and word count approximates tokens far better than char count. Override
# with CCD_MAX_TRANSCRIPT_WORDS; 0 disables the budget (use only n_turns).
DEFAULT_MAX_TRANSCRIPT_WORDS = 20000

# A regen attempt that raises a transient error is retried this many times
# total before the failure is surfaced to the dashboard. The observed
# transient failures — a dropped streaming socket (SubprocessFailed) and an
# empty model response (FragmentRejected: empty output) — clear on a second
# attempt far more often than not, so one retry absorbs the blip the user
# would otherwise have to read and dismiss.
MAX_ATTEMPTS = 2

# A trigger that arrives while a regen is already in flight is COALESCED:
# instead of SIGTERMing the in-flight run (the old "newest wins" behaviour,
# which meant nothing ever finished during active work because each turn
# killed the previous 3-5 min rebuild), we let it finish and queue exactly
# one follow-up. The exception is a job older than this many seconds — that
# long almost always means a wedged socket, so we supersede it and start
# fresh rather than wait forever.
STALE_SUPERSEDE_AFTER = 360.0

REQUIRED_FRAGMENT_MARKERS = (
    '<header class="session-header">',
    '<div class="pills">',
)

# FragmentRejected reasons that are worth a retry (the model returned nothing
# usable this time, but a fresh attempt usually succeeds). A structural
# violation like a stray markdown fence or a missing marker is the model
# misbehaving consistently — retrying just doubles the cost, so those fall
# through to a surfaced error.
_RETRYABLE_FRAGMENT_PREFIXES = ("empty output", "output too small")

# Marker injected into the subprocess env so the subagent's own Stop hook
# exits early — without this, the hook re-fires this registry recursively.
SUBAGENT_ENV_MARKER = "CLAUDE_DASHBOARD_SUBAGENT"

# Auth policy (single source of truth). The dashboard subagent runs on the
# SAME auth as the interactive Claude Code sessions it documents — the user's
# subscription (stored OAuth creds, kept in the OS keychain). Three ambient env
# vars hijack that auth if they leak into the server's environment:
#   - ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN divert `claude -p` to API-key
#     billing and fail closed ("Credit balance is too low") the moment that key
#     is unfunded.
#   - ANTHROPIC_BASE_URL redirects the subscription OAuth to a different endpoint
#     — e.g. Claude Code's own proxy when the server is (re)started from a Claude
#     Code shell — which rejects the subscription creds with a 401.
# We strip all three so the CLI always falls back to the keychain subscription
# against the default endpoint, regardless of what leaked into the environment.
AMBIENT_AUTH_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")


def build_subagent_env() -> dict:
    """Environment for every `claude -p` the plugin spawns. Marks the subagent
    (so its own Stop hook short-circuits) and enforces the subscription-auth
    policy above. Used by BOTH invoke_claude() and probe_auth() so generation
    and the health check can never diverge."""
    env = {**os.environ, SUBAGENT_ENV_MARKER: "1"}
    for var in AMBIENT_AUTH_VARS:
        env.pop(var, None)
    return env


# ─── JSONL curation (pure functions) ───────────────────────────────────

def read_jsonl(path: Path) -> list:
    """Stream-parse a session JSONL into a list of dicts."""
    out = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _is_pure_tool_result(user_event: dict) -> bool:
    content = user_event.get("message", {}).get("content")
    if not isinstance(content, list):
        return False
    for item in content:
        if not isinstance(item, dict):
            return False
        if item.get("type") != "tool_result":
            return False
    return True


def _is_turn_event(event: dict) -> bool:
    return event.get("type") in ("user", "assistant")


def split_into_turns(events: list) -> list:
    """Group consecutive user+assistant events into turn boundaries.

    A "turn" = one user message followed by all the assistant/tool_result
    events until the next non-tool_result user message. We rely on this to
    take the LAST N turns regardless of how many tool_use loops each had.
    """
    turns = []
    current: list = []
    for event in events:
        if not _is_turn_event(event):
            continue
        if event.get("type") == "user" and current and not _is_pure_tool_result(event):
            turns.append(current)
            current = []
        current.append(event)
    if current:
        turns.append(current)
    return turns


def estimate_words(payload) -> int:
    """Rough word count (a token approximation) used both for the transcript word
    budget and for prompt-size logging. Recurses through lists/dicts."""
    if isinstance(payload, str):
        return len(payload.split())
    if isinstance(payload, (list, tuple)):
        return sum(estimate_words(x) for x in payload)
    if isinstance(payload, dict):
        return sum(estimate_words(v) for v in payload.values())
    return 0


def select_turns_within_word_budget(turns: list, max_words: int) -> "tuple[list, int]":
    """Pick the suffix of whole turns (input ordered oldest->newest) that fits in
    max_words, ALWAYS keeping the most recent turn in full (recency over history).
    Turns are never truncated internally; whole OLDER turns are dropped instead.
    Returns (selected_turns, dropped_count). max_words <= 0 disables the budget."""
    if not turns:
        return [], 0
    selected: list = []
    total = 0
    for turn in reversed(turns):                 # newest first
        w = estimate_words(turn)
        # The most recent turn (first one added) is always kept in full, even if
        # it alone exceeds the budget; the budget only gates ADDING older turns.
        if selected and max_words > 0 and total + w > max_words:
            break
        selected.append(turn)
        total += w
    selected.reverse()                           # restore oldest->newest
    return selected, len(turns) - len(selected)


def render_curated_events(events: list) -> str:
    """Render curated events as a readable narrative for the subagent. Preserves
    thinking blocks and FULL tool_use/tool_result content -- no per-item
    truncation. Prompt size is bounded at TURN granularity by the word budget
    (see select_turns_within_word_budget), so every included turn shows all its
    tool calls in full."""
    lines = []
    for ev in events:
        role = ev.get("message", {}).get("role", ev.get("type"))
        content = ev.get("message", {}).get("content")

        if isinstance(content, str):
            lines.append(f"[{role.upper()}] text")
            lines.append(content)
            lines.append("")
            continue

        if not isinstance(content, list):
            continue

        lines.append(f"[{role.upper()}]")
        for item in content:
            if not isinstance(item, dict):
                continue
            t = item.get("type")
            if t == "text":
                lines.append(item.get("text", ""))
            elif t == "thinking":
                thinking = item.get("thinking", "") or item.get("text", "")
                lines.append(f"<thinking>\n{thinking}\n</thinking>")
            elif t == "tool_use":
                name = item.get("name", "?")
                inp = item.get("input", {})
                inp_json = json.dumps(inp, indent=2, ensure_ascii=False)
                lines.append(f"<tool_use name={name!r} id={item.get('id','?')!r}>")
                lines.append(inp_json)
                lines.append("</tool_use>")
            elif t == "tool_result":
                tid = item.get("tool_use_id", "?")
                inner = item.get("content")
                if isinstance(inner, str):
                    lines.append(f"<tool_result for={tid!r}>")
                    lines.append(inner)
                    lines.append("</tool_result>")
                elif isinstance(inner, list):
                    lines.append(f"<tool_result for={tid!r}>")
                    for sub in inner:
                        if isinstance(sub, dict):
                            if sub.get("type") == "text":
                                lines.append(sub.get("text", ""))
                            elif sub.get("type") == "tool_reference":
                                lines.append(f"[tool reference: {sub.get('name', '?')}]")
                            else:
                                lines.append(json.dumps(sub, ensure_ascii=False))
                    lines.append("</tool_result>")
        lines.append("")
    return "\n".join(lines)


def build_user_message(
    *,
    curated_events: list,
    current_dashboard: str,
    project_hash: str,
    session_uuid: str,
    dropped_turns: int = 0,
) -> str:
    """Assemble the curated transcript + current dashboard + closing ask.
    Order is "context → memory → ask" so the model lands on the ask last."""
    transcript = render_curated_events(curated_events)
    if dropped_turns > 0:
        transcript = (
            f"[{dropped_turns} older turn(s) elided to fit the transcript word "
            f"budget; recent turns shown in full below]\n\n" + transcript
        )
    current_block = (
        current_dashboard.strip()
        or "(no dashboard yet — this is the first turn for this chat)"
    )
    return (
        f"# Session\n"
        f"- project: {project_hash}\n"
        f"- session: {session_uuid}\n"
        f"- now: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n"
        f"\n"
        f"# Recent transcript (newest last)\n"
        f"{transcript}\n"
        f"\n"
        f"# Current dashboard fragment\n"
        f"{current_block}\n"
        f"\n"
        f"# Task\n"
        f"Update the dashboard fragment to reflect what just happened in the chat.\n"
        f"Preserve every existing data-row-id slug from the current dashboard.\n"
        f"Output ONLY the updated HTML body fragment, no fences, no preamble.\n"
    )


# ─── Validation + atomic write ─────────────────────────────────────────

def validate_fragment(body: str) -> "str | None":
    """None if `body` looks like a plausible dashboard fragment; else a
    short reason string. Caller treats non-None as "refuse to overwrite"."""
    stripped = body.lstrip()
    if not stripped:
        return "empty output"
    if len(body) < 500:
        return f"output too small ({len(body)} bytes)"
    if stripped.startswith("```"):
        return "output starts with markdown fence (```)"
    if stripped.lower().startswith("<!doctype"):
        return "output starts with <!doctype> — should be a fragment, not a full document"
    for marker in REQUIRED_FRAGMENT_MARKERS:
        if marker not in body:
            return f"missing required marker {marker!r}"
    return None


def atomic_write(session_dir: Path, body: str) -> None:
    """Write via tmp + os.replace. Original is unchanged unless rename succeeds.

    The tmp name is unique per call (mkstemp) rather than a fixed
    `dashboard.html.tmp`. With a shared name, two overlapping writes for the
    same session raced: the second writer's os.replace could fire after the
    first already consumed the shared tmp, raising FileNotFoundError. A
    per-call tmp removes that coupling entirely; on any failure we clean up
    our own tmp so a crashed write never leaves a stray file behind."""
    final = session_dir / "dashboard.html"
    fd, tmp_name = tempfile.mkstemp(dir=session_dir, prefix=".dashboard.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
        os.replace(tmp, final)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


# ─── Subprocess invocation ─────────────────────────────────────────────

@dataclass
class RunResult:
    body: str
    elapsed_seconds: float
    returncode: int
    stderr: str
    input_tokens: "int | None" = None
    output_tokens: "int | None" = None
    cost_usd: "float | None" = None
    duration_ms: "int | None" = None


def parse_cli_json(stdout: str) -> "tuple[str, dict]":
    """Parse `claude -p --output-format json` stdout into (body, metrics).
    The envelope carries the generated text under `result` plus a usage block.
    Falls back to (raw_stdout, {}) when stdout isn't that envelope, so a CLI
    version/flag quirk degrades to no-metrics rather than breaking generation."""
    try:
        d = json.loads(stdout)
    except (ValueError, TypeError):
        return stdout, {}
    if not isinstance(d, dict) or "result" not in d:
        return stdout, {}
    usage = d.get("usage") if isinstance(d.get("usage"), dict) else {}
    inp = usage.get("input_tokens")
    if isinstance(inp, int):
        # Count cached input toward the total so the tally reflects real prompt
        # size, not just the uncached delta.
        total_in = (
            inp
            + (usage.get("cache_creation_input_tokens") or 0)
            + (usage.get("cache_read_input_tokens") or 0)
        )
    else:
        total_in = None
    out = usage.get("output_tokens")
    metrics = {
        "input_tokens": total_in,
        "output_tokens": out if isinstance(out, int) else None,
        "cost_usd": d.get("total_cost_usd"),
        "duration_ms": d.get("duration_ms"),
    }
    return (d.get("result") or ""), metrics


def invoke_claude(
    *,
    system_prompt: str,
    user_message: str,
    model: str,
    timeout: float = DEFAULT_REGEN_TIMEOUT,
    on_proc: "Callable[[subprocess.Popen], None] | None" = None,
) -> RunResult:
    """Run `claude -p` headlessly. The `on_proc` callback hands the live
    Popen handle back to the caller so the Registry can SIGTERM it on
    supersede — by the time .wait() returns, the registry has already
    decided whether to interpret the returncode as cancel vs error.

    Flag rationale (carried forward from update.py):
      --setting-sources local      → don't inherit user-scope Stop hooks
                                     (otherwise: recursion + TTS chaos)
      --no-session-persistence     → don't write a ghost .jsonl to disk
      --system-prompt              → SYSTEM.md content drives the task
      --tools ""                   → text generation only, no FS access
    """
    cmd = [
        "claude",
        "-p",
        "--output-format", "json",
        "--setting-sources", "local",
        "--no-session-persistence",
        "--model", model,
        "--system-prompt", system_prompt,
        "--tools", "",
    ]
    env = build_subagent_env()

    start = time.monotonic()
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if on_proc is not None:
        on_proc(proc)
    try:
        stdout, stderr = proc.communicate(input=user_message, timeout=timeout)
    except subprocess.TimeoutExpired:
        # A wedged generation (stuck socket, runaway output) must never hang the
        # worker forever. Kill it, reap so the child can't linger, and raise a
        # NON-retryable timeout (a retry would just wait the full timeout again).
        proc.kill()
        try:
            proc.communicate(timeout=10)
        except Exception:
            pass
        elapsed = time.monotonic() - start
        raise RegenTimeout(
            f"claude -p exceeded {timeout:.0f}s wall-clock and was killed "
            f"(ran {elapsed:.1f}s)"
        )
    elapsed = time.monotonic() - start
    body, usage = parse_cli_json(stdout)
    return RunResult(
        body=body,
        elapsed_seconds=elapsed,
        returncode=proc.returncode,
        stderr=stderr,
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
        cost_usd=usage.get("cost_usd"),
        duration_ms=usage.get("duration_ms"),
    )


def probe_auth(model: str = DEFAULT_MODEL, timeout_s: float = 25.0) -> "tuple[bool, str]":
    """Can the dashboard subagent authenticate right now? Cheap startup health
    check that runs a tiny `claude -p` under the exact same auth policy as a
    real regen. Returns (ok, detail); on failure `detail` carries the CLI's own
    diagnostic (e.g. 'Credit balance is too low', 'Invalid API key') so the
    operator sees the real cause instead of silently-missing dashboards."""
    cmd = [
        "claude", "-p",
        "--setting-sources", "local",
        "--no-session-persistence",
        "--model", model,
        "--tools", "",
    ]
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=build_subagent_env(),
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        stdout, stderr = proc.communicate(input="Reply with: ok", timeout=timeout_s)
    except FileNotFoundError:
        return False, "claude CLI not found on PATH"
    except subprocess.TimeoutExpired:
        proc.kill()
        return False, f"probe timed out after {timeout_s:.0f}s"
    if proc.returncode == 0 and stdout.strip():
        return True, stdout.strip()[:200]
    detail = (stderr.strip() or stdout.strip() or f"claude -p exited {proc.returncode}")
    return False, detail[:300]


# ─── One full attempt ──────────────────────────────────────────────────

class FragmentRejected(Exception):
    """Raised when the subagent's output fails structural validation."""


class SubprocessFailed(Exception):
    """Raised when `claude -p` exits non-zero. stderr is captured."""


class RegenTimeout(SubprocessFailed):
    """Raised when `claude -p` exceeds the wall-clock timeout and is killed.
    A SubprocessFailed subclass so existing handling still catches it, but
    classified NON-retryable (retrying would just wait the full timeout again)."""


def run_once(
    *,
    plugin_dir: Path,
    projects_root: Path,
    project_hash: str,
    session_uuid: str,
    model: str = DEFAULT_MODEL,
    n_turns: int = DEFAULT_N_TURNS,
    timeout: float = DEFAULT_REGEN_TIMEOUT,
    max_words: int = DEFAULT_MAX_TRANSCRIPT_WORDS,
    metrics: "DashboardStore | None" = None,
    on_proc: "Callable[[subprocess.Popen], None] | None" = None,
) -> Path:
    """One complete regen attempt. Returns the dashboard.html path on
    success. Raises FragmentRejected on validation failure, SubprocessFailed
    on a non-zero exit, FileNotFoundError on missing JSONL/SYSTEM.md."""
    system_prompt_path = plugin_dir / "SYSTEM.md"
    jsonl_path = projects_root / project_hash / f"{session_uuid}.jsonl"
    session_dir = projects_root / project_hash / session_uuid

    if not jsonl_path.exists():
        raise FileNotFoundError(f"jsonl not found: {jsonl_path}")
    if not system_prompt_path.exists():
        raise FileNotFoundError(f"SYSTEM.md not found: {system_prompt_path}")

    session_dir.mkdir(parents=True, exist_ok=True)
    events = read_jsonl(jsonl_path)
    recent_turns = split_into_turns(events)[-n_turns:]
    selected_turns, dropped = select_turns_within_word_budget(recent_turns, max_words)
    curated = [e for turn in selected_turns for e in turn]

    dash_path = session_dir / "dashboard.html"
    current_dashboard = dash_path.read_text(encoding="utf-8", errors="replace") if dash_path.exists() else ""

    system_prompt = system_prompt_path.read_text(encoding="utf-8")
    user_message = build_user_message(
        curated_events=curated,
        current_dashboard=current_dashboard,
        project_hash=project_hash,
        session_uuid=session_uuid,
        dropped_turns=dropped,
    )

    _log.info(
        "regen %s/%s — events=%d curated=%d dropped_turns=%d prompt_words≈%d",
        project_hash, session_uuid[:8],
        len(events), len(curated), dropped, estimate_words(user_message),
    )

    result = invoke_claude(
        system_prompt=system_prompt,
        user_message=user_message,
        model=model,
        timeout=timeout,
        on_proc=on_proc,
    )

    if result.returncode != 0:
        # Capture EVERYTHING: claude -p sometimes writes diagnostics to
        # stdout and exits non-zero (seen in real failures where stderr
        # was empty). The `(empty)` marker is deliberate — without it we
        # couldn't distinguish "nothing was captured" from "we forgot to
        # look", which is exactly the diagnostic gap Sasha called out.
        # NB: RunResult.body holds what would otherwise be `result.stdout`
        # — the dataclass was named for the dashboard-fragment-output use.
        err = result.stderr.strip()
        out = result.body.strip()
        parts = [
            f"claude -p exited {result.returncode} after {result.elapsed_seconds:.1f}s",
            "--- stderr ---",
            (err[:2000] if err else "(empty)"),
            "--- stdout ---",
            (out[:2000] if out else "(empty)"),
        ]
        raise SubprocessFailed("\n".join(parts))

    reason = validate_fragment(result.body)
    if reason is not None:
        raise FragmentRejected(
            f"{reason} (first 200 chars: {result.body[:200]!r})"
        )

    atomic_write(session_dir, result.body)
    _log.info(
        "regen %s/%s — wrote %d bytes in %.1fs",
        project_hash, session_uuid[:8],
        len(result.body), result.elapsed_seconds,
    )
    if metrics is not None:
        try:
            metrics.record(
                project_hash=project_hash,
                session_uuid=session_uuid,
                model=model,
                status="ok",
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cost_usd=result.cost_usd,
                duration_ms=result.duration_ms,
                wall_ms=int(result.elapsed_seconds * 1000),
            )
        except Exception:
            _log.warning(
                "metrics record failed for %s/%s",
                project_hash, session_uuid[:8], exc_info=True,
            )
    return dash_path


# ─── Registry ──────────────────────────────────────────────────────────

@dataclass
class JobRecord:
    project_hash: str
    session_uuid: str
    started_at: float
    state: str  # "running" | "failed"
    proc: "subprocess.Popen | None" = None
    error: "str | None" = None
    last_attempt_at: "float | None" = None
    superseded: bool = False
    # Set when a trigger arrives while this job is in flight: the job runs to
    # completion, then schedules exactly one follow-up so the turns that
    # arrived mid-run get captured without supersede churn.
    rerun_requested: bool = False


class Registry:
    """Tracks at most one in-flight regen per session_uuid and exposes
    state for the index UI. Thread-safe under a single RLock."""

    def __init__(
        self,
        *,
        plugin_dir: Path,
        projects_root: Path,
        model: str = DEFAULT_MODEL,
        n_turns: int = DEFAULT_N_TURNS,
        timeout: float = DEFAULT_REGEN_TIMEOUT,
        max_words: int = DEFAULT_MAX_TRANSCRIPT_WORDS,
        metrics: "DashboardStore | None" = None,
        on_success: "Callable[[str, str], None] | None" = None,
        on_failure: "Callable[[str, str, str, str], None] | None" = None,
    ):
        self._plugin_dir = plugin_dir
        self._projects_root = projects_root
        self._model = model
        self._n_turns = n_turns
        self._timeout = timeout
        self._max_words = max_words
        self._metrics = metrics
        self._lock = threading.RLock()
        self._jobs: "dict[str, JobRecord]" = {}
        # Fired after a regen completes successfully — used by serve.py to
        # auto-touch the recents queue so spawned-but-never-opened child
        # dashboards (e.g. from a fresh worktree) surface in the quick-jump
        # strip without the user having to find them manually.
        self._on_success = on_success
        # Fired after a regen genuinely fails (not a supersede). Signature:
        # (project_hash, session_uuid, kind, message). serve.py persists
        # the error into the per-chat state.json so it survives the
        # transient in-memory `failed` record's eviction by the next run.
        self._on_failure = on_failure

    # ─── Public API ────────────────────────────────────────────────

    def trigger(self, project_hash: str, session_uuid: str) -> dict:
        """Schedule a regen for this session.

        If a job is already in flight and is not suspiciously old, coalesce:
        flag it for a single follow-up and return its snapshot without
        starting (or killing) anything — this run finishes, then reruns once.
        Otherwise (no job, a finished/failed record, or a wedged stale job)
        cancel whatever is there and start fresh.
        """
        with self._lock:
            old = self._jobs.get(session_uuid)
            if old is not None and old.state == "running":
                age = time.time() - old.started_at
                if age < STALE_SUPERSEDE_AFTER:
                    old.rerun_requested = True
                    return self._snapshot_locked(old)
                # Fall through: the in-flight job is old enough to be wedged.
            if old is not None:
                self._cancel_locked(old)
            new = JobRecord(
                project_hash=project_hash,
                session_uuid=session_uuid,
                started_at=time.time(),
                state="running",
            )
            self._jobs[session_uuid] = new
            snapshot = self._snapshot_locked(new)

        thread = threading.Thread(
            target=self._run, args=(new,), daemon=True,
            name=f"regen-{session_uuid[:8]}",
        )
        thread.start()
        return snapshot

    def state_for(self, session_uuid: str) -> "dict | None":
        """Public state snapshot for one session, or None if no record."""
        with self._lock:
            r = self._jobs.get(session_uuid)
            return self._snapshot_locked(r) if r is not None else None

    def resolve_project_hash(self, session_uuid: str) -> "str | None":
        """Find the project_hash dir that owns a session_uuid by looking
        for `<projects_root>/*/<uuid>.jsonl`. Used so the HTTP API accepts
        a bare session UUID — the hook doesn't need to compute the hash."""
        for proj_dir in self._projects_root.iterdir():
            if not proj_dir.is_dir():
                continue
            if (proj_dir / f"{session_uuid}.jsonl").is_file():
                return proj_dir.name
        return None

    # ─── Internals ─────────────────────────────────────────────────

    def _snapshot_locked(self, r: JobRecord) -> dict:
        return {
            "state": r.state,
            "since": int(r.started_at),
            "lastAttemptAt": int(r.last_attempt_at) if r.last_attempt_at else None,
            "error": r.error,
        }

    def _cancel_locked(self, r: JobRecord) -> None:
        """Mark `r` superseded and SIGTERM its subprocess if still alive.
        Caller holds the lock."""
        r.superseded = True
        proc = r.proc
        if proc is not None and proc.poll() is None:
            _log.info(
                "supersede %s/%s — terminating pid %d",
                r.project_hash, r.session_uuid[:8], proc.pid,
            )
            try:
                proc.terminate()
            except OSError:
                pass
            # Fire-and-forget SIGKILL fallback in a tiny daemon thread so
            # the lock-holder doesn't block on it. communicate() in the
            # other thread will unblock either way.
            threading.Thread(
                target=self._sigkill_after_grace,
                args=(proc,),
                daemon=True,
            ).start()

    @staticmethod
    def _sigkill_after_grace(proc: subprocess.Popen, grace_s: float = 0.5) -> None:
        end = time.monotonic() + grace_s
        while time.monotonic() < end:
            if proc.poll() is not None:
                return
            time.sleep(0.05)
        try:
            proc.kill()
        except OSError:
            pass

    def _run(self, record: JobRecord) -> None:
        """Daemon-thread worker: runs run_once (retrying transient failures),
        then updates state under the lock. If the record was superseded
        mid-run, leaves state to the replacement record. On completion —
        success OR a surfaced failure — honours a coalesced rerun request."""

        def attach_proc(p: subprocess.Popen) -> None:
            with self._lock:
                record.proc = p

        attempt = 0
        while True:
            attempt += 1
            # Bail before spending an attempt if we've been superseded or
            # replaced (a stale-job supersede started a fresh record).
            with self._lock:
                if record.superseded or self._jobs.get(record.session_uuid) is not record:
                    return

            try:
                run_once(
                    plugin_dir=self._plugin_dir,
                    projects_root=self._projects_root,
                    project_hash=record.project_hash,
                    session_uuid=record.session_uuid,
                    model=self._model,
                    n_turns=self._n_turns,
                    timeout=self._timeout,
                    max_words=self._max_words,
                    metrics=self._metrics,
                    on_proc=attach_proc,
                )
            except Exception as e:
                error_kind = type(e).__name__
                # Two views of the same error:
                # - `error_full` is the unredacted message including stderr/
                #   stdout dumps when applicable. It's what the persisted
                #   regenErrors entry gets — the user expanded the banner
                #   to read this; truncating it defeats the point.
                # - `error_short` is the 200-char version used for the
                #   in-memory chip tooltip, where the user just needs a hint.
                error_full = str(e).strip()
                error_short = _short_error(e)
                with self._lock:
                    # Distinguish supersede-induced subprocess failures from
                    # real errors. If we were superseded the new record owns
                    # state, so we drop ours quietly without firing on_failure.
                    if record.superseded:
                        _log.info(
                            "supersede %s/%s — %s",
                            record.project_hash, record.session_uuid[:8],
                            error_kind,
                        )
                        return
                    if self._jobs.get(record.session_uuid) is not record:
                        return
                    retry = attempt < MAX_ATTEMPTS and _is_retryable(e)
                    if not retry:
                        record.state = "failed"
                        record.error = error_short
                        record.last_attempt_at = time.time()
                        record.proc = None
                if retry:
                    _log.info(
                        "regen retry %s/%s — attempt %d/%d after %s: %s",
                        record.project_hash, record.session_uuid[:8],
                        attempt, MAX_ATTEMPTS, error_kind, error_short,
                    )
                    continue
                _log.warning(
                    "regen failed %s/%s — %s: %s",
                    record.project_hash, record.session_uuid[:8],
                    error_kind, error_short,
                )
                # Full diagnostic — what the persisted record sees, also
                # available in server.log for cross-session grep.
                _log.info(
                    "regen-error detail %s/%s:\n%s",
                    record.project_hash, record.session_uuid[:8], error_full,
                )
                # Hook fires OUTSIDE the lock — the callback writes to disk
                # (per-chat state.json) and may block briefly; we don't want
                # to hold up other sessions.
                if self._on_failure is not None:
                    try:
                        self._on_failure(
                            record.project_hash, record.session_uuid,
                            error_kind, error_full,
                        )
                    except Exception:
                        _log.exception("on_failure callback raised")
                # Record the failure in the metrics db too, so regen_metrics.status
                # reflects real failure rate over time (success rows carry
                # tokens/latency; failure rows carry just the outcome).
                if self._metrics is not None:
                    try:
                        self._metrics.record(
                            project_hash=record.project_hash,
                            session_uuid=record.session_uuid,
                            model=self._model,
                            status="failed",
                        )
                    except Exception:
                        _log.warning("metrics record (failed) raised", exc_info=True)
                # A failed regen still consumed the turns that triggered it;
                # honour any rerun queued meanwhile so we retry on fresh state.
                self._maybe_rerun(record)
                return

            # Success.
            fire_on_success = False
            with self._lock:
                if not record.superseded and self._jobs.get(record.session_uuid) is record:
                    # Clear the record so the UI infers "current" from file
                    # mtimes.
                    del self._jobs[record.session_uuid]
                    fire_on_success = True
            # Callbacks fire OUTSIDE the lock — they shouldn't block other
            # regen jobs and may themselves take the recents lock.
            if fire_on_success and self._on_success is not None:
                try:
                    self._on_success(record.project_hash, record.session_uuid)
                except Exception:
                    _log.exception("on_success callback raised")
            self._maybe_rerun(record)
            return

    def _maybe_rerun(self, record: JobRecord) -> None:
        """If a trigger was coalesced onto this job while it ran, start one
        fresh regen now so the mid-run turns get captured. Clears the flag
        first so a single queued request produces exactly one follow-up."""
        with self._lock:
            rerun = record.rerun_requested
            record.rerun_requested = False
        if rerun:
            _log.info(
                "regen coalesced-rerun %s/%s",
                record.project_hash, record.session_uuid[:8],
            )
            self.trigger(record.project_hash, record.session_uuid)


def _short_error(e: BaseException) -> str:
    """Trim error messages for the UI — full text is in the log file."""
    msg = str(e).strip()
    if len(msg) > 200:
        msg = msg[:197] + "..."
    return msg


def _is_retryable(e: BaseException) -> bool:
    """Whether a failed attempt is worth one more shot before surfacing.

    SubprocessFailed covers dropped streaming sockets and non-zero `claude -p`
    exits — overwhelmingly transient. FragmentRejected is only retried when
    the model returned nothing usable (empty / too small); a structural
    violation is consistent misbehaviour that a retry won't fix.
    """
    if isinstance(e, RegenTimeout):
        return False
    if isinstance(e, SubprocessFailed):
        return True
    if isinstance(e, FragmentRejected):
        return str(e).lstrip().startswith(_RETRYABLE_FRAGMENT_PREFIXES)
    return False
