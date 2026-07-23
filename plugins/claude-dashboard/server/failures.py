"""Turns a raw rebuild failure into the presentation every surface renders.

A presentation is:
  kind      machine name of the rule that matched
  severity  action | warning | bug
  title     one plain sentence saying what happened
  body      what happens next, and what to do if anything
  actions   things the person can act on: a command to run, or a link
  detail    the raw text, for a collapsed technical view
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlencode

REPORT_URL = "https://github.com/Svtoo/atk-registry/issues"
PLUGIN = "claude-dashboard"
REPORT_LABELS = f"bug,plugin: {PLUGIN}"


def _command(label: str, value: str) -> dict:
    """A shell command, shown as text with a copy button beside it."""
    return {"label": label, "kind": "command", "value": value}


def _link(label: str, value: str) -> dict:
    return {"label": label, "kind": "link", "value": value}


def _copy(label: str, value: str) -> dict:
    """A copy-to-clipboard action for `value`."""
    return {"label": label, "kind": "copy", "value": value}


def _report_actions(summary: str, kind: str) -> list:
    """A pre-filled new-issue link plus a copy of that link, for a browser pane
    that is not signed in to GitHub."""
    body = (
        "## What happened\n"
        f"{summary}\n\n"
        "## What you were doing\n"
        "Describe what the chat was doing when this appeared.\n\n"
        "## Diagnostics\n"
        "Use Copy diagnostics on the dashboard message and paste here. It is\n"
        "measurements only, nothing from your conversation.\n\n"
        "```\n\n```\n\n"
        "## Anything else\n"
    )
    query = urlencode({"title": f"[{PLUGIN}] {summary}",
                       "body": body,
                       "labels": REPORT_LABELS})
    url = f"{REPORT_URL}/new?{query}"
    return [_link("Report it on GitHub", url), _copy("Copy link", url)]


# Measurements that describe a failure without describing the conversation.
# The project hash stays out: it is a slug of the filesystem path and would put
# the person's username and directory layout into a public issue.
_SAFE_MEASUREMENTS = (
    ("model", "Model"),
    ("prompt_words", "Prompt size (words)"),
    ("input_tokens", "Input tokens"),
    ("output_tokens", "Output tokens"),
    ("output_bytes", "Output (bytes)"),
    ("wall_ms", "Wall time (ms)"),
    ("attempts", "Attempts"),
)


def _diagnostics(kind: str, context: dict) -> list:
    """A metadata-only picture of the failure, safe to paste in public."""
    row = context.get("measurements") or {}
    items = [{"label": "Plugin", "value": PLUGIN},
             {"label": "Failure", "value": kind or "unknown"}]
    when = row.get("ts")
    if when:
        items.append({"label": "When (UTC)",
                      "value": datetime.fromtimestamp(when, timezone.utc)
                                       .strftime("%Y-%m-%d %H:%M:%S")})
    limit = context.get("timeout_s")
    if limit:
        items.append({"label": "Time limit (s)", "value": int(limit)})
    for field, label in _SAFE_MEASUREMENTS:
        value = row.get(field)
        if value not in (None, ""):
            items.append({"label": label, "value": value})
    return items


def _diagnostics_text(items: list) -> str:
    return "\n".join(f"{item['label']}: {item['value']}" for item in items)


def _present(kind, severity, title, body, actions, detail, diagnostics=()) -> dict:
    return {
        "kind": kind,
        "severity": severity,
        "title": title,
        "body": body,
        "actions": list(actions),
        "detail": detail,
        "diagnostics": list(diagnostics),
    }


# ─── rules: (does this match?, how to present it) ──────────────────────

def _is_auth(kind: str, message: str) -> bool:
    low = message.lower()
    return "401" in message and ("authenticate" in low or "authentication" in low)


def _auth(kind, message, ctx) -> dict:
    return _present(
        "auth_expired", "action",
        "Your Claude CLI sign in has expired, so dashboards have stopped updating.",
        "Run this in your terminal to sign in again. Updates start on their own "
        "afterwards, with no restart needed.",
        [_command("Sign in to the Claude CLI", "claude auth login")],
        message,
    )


def _is_too_long(kind: str, message: str) -> bool:
    return "prompt is too long" in message.lower()


def _too_long(kind, message, ctx) -> dict:
    return _present(
        "prompt_too_long", "bug",
        "Something went wrong on our side. This update was too large to send.",
        "That is a bug in how we trim the conversation, not something you did or "
        "can fix. Your dashboard will try again on the next turn.",
        _report_actions("An update was too large to send", "prompt_too_long"),
        message,
    )


def _is_timeout(kind: str, message: str) -> bool:
    return kind == "RegenTimeout"


def _timeout(kind, message, ctx) -> dict:
    limit = ctx.get("timeout_s")
    typical = ctx.get("typical_s")
    title = (
        f"This update was stopped after {limit:.0f} seconds, the current time limit."
        if limit else "This update ran out of time and was stopped."
    )
    body = "It will try again on the next turn."
    if typical:
        body = (f"Updates for this chat usually take about {typical:.0f} seconds. " + body)
    body += " If this keeps happening, raise the limit in Settings."
    return _present(
        "regen_timeout", "warning", title, body,
        [_link("Settings", "/settings"), _link("Stats", "/stats")],
        message,
    )


_RULES = (
    (_is_auth, _auth),
    (_is_too_long, _too_long),
    (_is_timeout, _timeout),
)


def _generic(kind, message, ctx) -> dict:
    return _present(
        "unknown", "warning",
        "A dashboard update did not finish.",
        "It will try again on the next turn. If you keep seeing this, please report it.",
        _report_actions("A dashboard update did not finish", kind or "unknown"),
        message,
    )


def is_permanent(kind: str, message: str) -> bool:
    """True when trying again cannot help, because the same input produces the
    same result: an oversized prompt is re-sent unchanged, and an expired sign
    in is still expired a second later. Lives here so the shape of a failure is
    recognised in one place."""
    return _is_too_long(kind or "", message or "") or _is_auth(kind or "", message or "")


def present(kind: str, message: str, **context) -> dict:
    """Describe one failure for a person. `context` may carry timeout_s (the
    configured limit), typical_s (this chat's usual rebuild time) and
    measurements (the numbers recorded for the rebuild that failed)."""
    kind = kind or ""
    message = message or ""
    for matches, build in _RULES:
        if matches(kind, message):
            result = build(kind, message, context)
            break
    else:
        result = _generic(kind, message, context)

    result["diagnostics"] = _diagnostics(result["kind"], context)
    if any(a["kind"] == "link" and "/issues/new" in a["value"] for a in result["actions"]):
        result["actions"].append(
            _copy("Copy diagnostics", _diagnostics_text(result["diagnostics"])))
    return result
