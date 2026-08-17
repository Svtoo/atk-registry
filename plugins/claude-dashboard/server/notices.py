"""The catalog of everything this dashboard can tell a person is wrong.

Producers raise a code. This module owns every user-facing word, so no other
module may write error prose.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

CATALOG_VERSION = 1

SEVERITY_RANK = {"blocked": 0, "bug": 1, "degraded": 2, "info": 3}

REPORT_URL = "https://github.com/Svtoo/atk-registry/issues"
PLUGIN = "claude-dashboard"
REPORT_LABELS = f"bug,plugin: {PLUGIN}"

OVERLAY_PATH = Path(__file__).resolve().parent.parent / "templates" / "notices.json"

# Wording an overlay may replace. Everything else is policy or code.
OVERLAY_FIELDS = ("title", "what", "label", "explain")

_log = logging.getLogger("claude-dashboard.notices")
_CACHE: dict = {}
_PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")


@dataclass(frozen=True)
class Step:
    text: str
    command: str = ""
    href: str = ""
    href_label: str = ""


@dataclass(frozen=True)
class Notice:
    code: str
    severity: str            # blocked | degraded | bug | info
    scope: str               # app | page | chat | field
    title: str
    what: str
    label: str               # 2-4 words, for chips and pills
    steps: tuple = ()
    explain: str = ""
    dismiss: str = "none"    # none | ack | auto
    self_heals: bool = False
    report: bool = False


def _n(code, severity, scope, title, what, label, steps=(), **kw) -> Notice:
    return Notice(code=code, severity=severity, scope=scope, title=title,
                  what=what, label=label, steps=tuple(steps), **kw)


# ─── account: can summaries be generated at all ────────────────────────

_ACCOUNT = (
    _n("account.check_pending", "info", "app",
       "Checking that Claude Code can write summaries.",
       "This takes a few seconds when the dashboard starts. Nothing is wrong "
       "yet — this page will say so if the check fails.",
       "checking",
       self_heals=True),

    _n("account.signed_out", "blocked", "app",
       "Claude Code is signed out on this computer, so your dashboards have "
       "stopped updating.",
       "This dashboard has no account or password of its own. Every summary is "
       "written by the Claude Code app already installed on this computer, "
       "using the same Claude subscription you sign in to there. That sign in "
       "has lapsed, so no new summaries can start. Nothing in your chats was "
       "lost and the dashboards you already have are unchanged — they will "
       "just stop keeping up until you sign in again.",
       "signed out",
       steps=(
           Step("Open a terminal window."),
           Step("Run this, then follow the prompt in your browser.",
                command="claude auth login"),
           Step("Come back to this page. Summaries start again after your next "
                "reply — there is nothing to restart."),
           Step("Still stuck? Ask the app what it thinks your status is.",
                command="claude auth status"),
       ),
       explain=(
           "The dashboard server itself only reads files on this computer and "
           "needs no account. But turning a conversation into a summary needs "
           "a model, and this plugin deliberately borrows your Claude Code "
           "subscription for that instead of asking you for a key of its own "
           "— it even ignores any key it finds in your environment, so there "
           "is only ever one place to sign in: the Claude Code app."),
       self_heals=True),

    _n("account.usage_limit", "blocked", "app",
       "Your Claude usage limit has been reached, so new summaries have paused.",
       "Summaries are written by the Claude Code app on this computer using "
       "your Claude subscription — the same one you use in the app itself. "
       "That subscription has hit its limit, so the app is refusing new work. "
       "This is not a sign-in problem and nothing is broken. Your existing "
       "dashboards are intact and summaries resume once your limit resets. "
       "There is nothing to buy and nothing to restart.",
       "usage limit",
       steps=(
           Step("Wait for your limit to reset, then keep working — your next "
                "reply picks up where this left off."),
           Step("Check what the app reports about your account.",
                command="claude auth status"),
       ),
       self_heals=True),

    _n("account.no_credit", "blocked", "app",
       "The Claude account writing your summaries has run out of credit.",
       "Summaries are written by the Claude Code app on this computer, using "
       "whichever account is signed in there. That account is billed by credit "
       "rather than by a subscription, and its balance is empty, so no new "
       "summaries can start. Nothing on this computer is broken and your "
       "existing dashboards are unchanged.",
       "no credit",
       steps=(
           Step("Check which account is signed in.", command="claude auth status"),
           Step("If that is not the account you meant to use, sign in to the "
                "right one.", command="claude auth login"),
           Step("If it is the right account, add credit to it in the Claude "
                "Console, then keep working — your next reply picks this up."),
       ),
       self_heals=True),

    _n("account.cli_missing", "blocked", "app",
       "The Claude Code app is not where this dashboard can look for it.",
       "Every summary is produced by running the `claude` command that ships "
       "with Claude Code. That command is not reachable from where this "
       "dashboard runs, so nothing can be generated. Your chats and existing "
       "dashboards are untouched.",
       "app not found",
       steps=(
           Step("Check whether the command is reachable, then read the answer.",
                command="command -v claude"),
           Step("If that printed a file location, the dashboard is looking in "
                "the wrong place — restart it from the same terminal where "
                "the command works.",
                command="atk restart claude-dashboard"),
           Step("If it printed nothing, Claude Code is not installed for this "
                "account. Install it, then restart the dashboard.",
                command="atk restart claude-dashboard"),
       )),

    _n("account.model_denied", "blocked", "app",
       "Your Claude account cannot use the model this dashboard is set to.",
       "Summaries are written with a specific Claude model. Your subscription "
       "does not have access to the one configured here, so every attempt is "
       "refused. Your existing dashboards are unaffected.",
       "model unavailable",
       steps=(
           Step("Pick a model your account can use.",
                href="/settings", href_label="Settings"),
           Step("Check what your account reports.", command="claude auth status"),
       )),

    _n("account.check_unclear", "degraded", "app",
       "The dashboard could not confirm whether Claude Code is able to write "
       "summaries.",
       "The startup check did not finish in time. Summaries may still work — "
       "this only means the check itself was inconclusive. If dashboards stop "
       "keeping up, the next failure will say exactly why.",
       "check failed",
       steps=(Step("Confirm it yourself.", command="claude auth status"),),
       self_heals=True),
)

# ─── rebuild: one summary failed ───────────────────────────────────────

_REBUILD = (
    _n("rebuild.timeout", "degraded", "chat",
       "This summary was stopped for taking too long.",
       "The current time limit is {limit_s} seconds. Summaries for this chat "
       "usually take about {typical_s} seconds. It will try again after your "
       "next reply. If it keeps happening, raise the limit.",
       "took too long",
       steps=(
           Step("Raise the time limit.", href="/settings", href_label="Settings"),
           Step("See how long summaries normally take.",
                href="/stats", href_label="Stats"),
       ),
       dismiss="ack", self_heals=True),

    _n("rebuild.too_large", "bug", "chat",
       "Something went wrong on our side: this summary was too large to send.",
       "That is a fault in how we trim the conversation before sending it, not "
       "something you did or can fix. Your dashboard will try again after your "
       "next reply, and long chats often succeed on a later attempt.",
       "too large",
       steps=(
           Step("Nothing to do — it retries after your next reply."),
           Step("If it keeps happening on this chat, report it."),
       ),
       dismiss="ack", self_heals=True, report=True),

    _n("rebuild.bad_output", "bug", "chat",
       "Something went wrong on our side: the summary came back in a form we "
       "could not use.",
       "The model's answer did not match the shape this dashboard expects, so "
       "it was thrown away rather than shown to you half-broken. Your previous "
       "dashboard is still on screen and unchanged. It tries again after your "
       "next reply.",
       "bad output",
       steps=(
           Step("Nothing to do — it retries after your next reply."),
           Step("If this chat keeps producing it, report it."),
       ),
       dismiss="ack", self_heals=True, report=True),

    _n("rebuild.failed", "degraded", "chat",
       "A summary for this chat did not finish.",
       "The reason is kept with this message under Technical detail. Nothing "
       "was lost — your existing dashboard is unchanged and a fresh attempt "
       "starts after your next reply. If it keeps happening on the same chat, "
       "that is worth reporting.",
       "did not finish",
       steps=(
           Step("Rebuild it now instead of waiting, with the rebuild button in "
                "this page's header."),
           Step("If it keeps happening, report it."),
       ),
       dismiss="ack", self_heals=True, report=True),

    _n("rebuild.chat_vanished", "info", "chat",
       "This chat's transcript is gone, so its summary was not rebuilt.",
       "The conversation file it reads was deleted or moved. The dashboard you "
       "are looking at is the last one that was built.",
       "chat removed",
       dismiss="auto"),
)

# ─── chat: this chat's own state ───────────────────────────────────────

_CHAT = (
    _n("chat.pending", "info", "page",
       "Waiting for your first reply before this dashboard can be built.",
       "This pane shows a live summary of this chat — the key facts, "
       "decisions, open questions and to-dos, rebuilt after every reply. It is "
       "generated from the conversation, so there is nothing to show until the "
       "agent responds. It will appear here by itself. No action needed.",
       "waiting",
       self_heals=True),

    _n("chat.gone", "blocked", "page",
       "This chat no longer exists.",
       "There is no conversation on this computer with this address. It was "
       "deleted, or the link is wrong. Nothing more will load here.",
       "chat not found",
       steps=(Step("Pick a chat that still exists.",
                   href="/", href_label="All projects"),)),
)

# ─── net: the browser cannot reach us ──────────────────────────────────

_NET = (
    _n("net.server_down", "blocked", "page",
       "The dashboard server is not answering, so nothing here is updating.",
       "This page is still showing whatever it last loaded, so numbers and "
       "statuses may be out of date. Once the server is running again, this "
       "page catches up the next time it refreshes.",
       "server down",
       steps=(
           Step("Start it from a terminal.", command="atk start claude-dashboard"),
           Step("Check whether it is already running.",
                command="atk status claude-dashboard"),
       )),

    _n("net.page_failed", "degraded", "page",
       "Part of this page could not be loaded.",
       "The server answered, but not with something this page could use. What "
       "you can see is still accurate; anything missing is missing, not zero.",
       "did not load",
       steps=(Step("Reload the page."),)),

    _n("net.action_failed", "degraded", "field",
       "That did not go through.",
       "Your click reached the page but not the server, so nothing was "
       "changed. Try it again.",
       "did not go through",
       steps=(Step("Try it again."),),
       dismiss="auto"),

    _n("net.diagram_failed", "info", "page",
       "A diagram in this dashboard could not be drawn.",
       "The drawing library is fetched from the internet and did not arrive. "
       "The diagram's text is shown as-is. Everything else on this page is fine.",
       "diagram not drawn",
       dismiss="auto"),
)

# ─── page: this request cannot be served ───────────────────────────────

_PAGE = (
    _n("page.not_found", "blocked", "page",
       "That page does not exist.",
       "The address you opened does not match a project or a chat this "
       "dashboard knows about. It may have been renamed, or the chat may have "
       "been deleted.",
       "not found",
       steps=(Step("Go to the list of projects and pick one from there.",
                   href="/", href_label="All projects"),)),

    _n("page.bad_address", "blocked", "page",
       "That address is not one this dashboard can read.",
       "Part of the link is malformed, so there is nothing to look up. This "
       "usually means a hand-edited or truncated web address.",
       "bad address",
       steps=(Step("Start from the list of projects.",
                   href="/", href_label="All projects"),)),

    _n("page.not_allowed", "blocked", "page",
       "That file is outside what this dashboard will serve.",
       "The dashboard only serves files from your Claude projects folder and "
       "its own assets. The address you opened points somewhere else, so it "
       "was refused.",
       "not allowed",
       steps=(Step("Start from the list of projects.",
                   href="/", href_label="All projects"),)),

    _n("page.not_ready", "degraded", "page",
       "The dashboard is still starting up, so this page is not ready yet.",
       "Some parts of the dashboard finish loading a moment after the server "
       "starts. This page needs one of them and it is not there yet.",
       "still starting",
       steps=(Step("Reload the page in a moment."),),
       self_heals=True),

    _n("page.wrong_type", "bug", "page",
       "Something went wrong on our side: this page sent a badly formed request.",
       "Only this dashboard's own pages talk to this address, so a rejected "
       "request means a fault in our code, not in anything you did.",
       "bad request",
       steps=(
           Step("Reload the page."),
           Step("If it keeps happening, report it."),
       ),
       report=True),

    _n("page.internal", "bug", "page",
       "Something went wrong inside the dashboard.",
       "This is a fault in the dashboard itself, not something you did. The "
       "page you asked for could not be built. Your chats and existing "
       "dashboards are not affected.",
       "internal fault",
       steps=(
           Step("Reload the page — one-off faults usually clear.",
                href="/", href_label="All projects"),
           Step("If it keeps happening, report it."),
       ),
       report=True),
)

# ─── settings, storage, and this catalog itself ────────────────────────

_OTHER = (
    _n("settings.rejected", "degraded", "field",
       "{reason}",
       "Your other settings were not changed, and nothing was saved. Pick a "
       "different value and save again.",
       "not accepted",
       steps=(Step("Pick a different value and save again."),),
       dismiss="auto"),

    _n("settings.not_saved", "blocked", "field",
       "Your change could not be written to disk, so it will be lost when the "
       "dashboard restarts.",
       "The settings file could not be written — usually a permissions problem "
       "on the plugin folder. The value is in effect right now; it just will "
       "not survive a restart.",
       "cannot save",
       steps=(Step("Check whether the settings file is writable.",
                   command="ls -l ~/.atk/plugins/claude-dashboard/.env"),)),

    _n("store.degraded", "degraded", "app",
       "The dashboard's records of past summaries could not be read or written.",
       "Counts and costs may be incomplete. This affects the Stats page and "
       "the figures at the bottom of each dashboard. Summaries themselves are "
       "unaffected and keep generating normally.",
       "history incomplete",
       steps=(Step("See what is recorded.", href="/stats", href_label="Stats"),),
       dismiss="ack"),

    _n("notice.copy_unreadable", "bug", "app",
       "Something went wrong on our side: this dashboard's wording file could "
       "not be read.",
       "Every message you see is coming from the wording built into the "
       "dashboard. Nothing else is affected, and no other part of the "
       "dashboard depends on that file.",
       "wording file broken",
       steps=(
           Step("Check the file for a syntax error.",
                command="python3 -m json.tool "
                        "~/.atk/plugins/claude-dashboard/templates/notices.json"),
           Step("Delete it to fall back cleanly, then reload this page."),
       ),
       report=True),
)

_DEFAULT_COPY: dict = {
    n.code: n for n in (_ACCOUNT + _REBUILD + _CHAT + _NET + _PAGE + _OTHER)
}

# Raised by the browser itself; pre-rendered because they must render with the
# server unreachable.
CLIENT_CODES = ("net.server_down", "net.page_failed", "net.action_failed",
                "net.diagram_failed", "chat.gone", "chat.pending", "rebuild.failed")

FALLBACK_CODE = "rebuild.failed"

# Trying again cannot help: the same input produces the same result.
_PERMANENT = frozenset({
    "account.signed_out", "account.usage_limit", "account.no_credit",
    "account.cli_missing", "account.model_denied", "rebuild.too_large",
})


# ─── the wording overlay ───────────────────────────────────────────────

def _apply_overlay(defaults: dict, raw: dict) -> dict:
    out = dict(defaults)
    for code, patch in raw.items():
        base = out.get(code)
        if base is None or not isinstance(patch, dict):
            _log.warning("notices: overlay names unknown code %s", code)
            continue
        fields = {f: patch[f] for f in OVERLAY_FIELDS
                  if isinstance(patch.get(f), str) and patch[f].strip()}
        steps = patch.get("steps")
        if isinstance(steps, list):
            # Positional and text-only: an overlay rewords a step, never adds,
            # removes, or changes its command.
            fields["steps"] = tuple(
                replace(s, text=steps[i]["text"])
                if (i < len(steps) and isinstance(steps[i], dict)
                    and isinstance(steps[i].get("text"), str) and steps[i]["text"].strip())
                else s
                for i, s in enumerate(base.steps)
            )
        if fields:
            out[code] = replace(base, **fields)
    return out


def _load() -> tuple:
    try:
        stat = OVERLAY_PATH.stat()
        key = (str(OVERLAY_PATH), stat.st_mtime_ns, stat.st_size)
    except OSError:
        key = (str(OVERLAY_PATH), None, None)
    cached = _CACHE.get("loaded")
    if cached is not None and _CACHE.get("key") == key:
        return cached
    if key[1] is None:
        loaded = (_DEFAULT_COPY, ())
    else:
        try:
            raw = json.loads(OVERLAY_PATH.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("top level must be an object")
            loaded = (_apply_overlay(_DEFAULT_COPY, raw), ())
        except Exception as e:  # noqa: BLE001 — a live-edited file must never 500
            _log.warning("notices: overlay unreadable (%s), using built-in wording", e)
            loaded = (_DEFAULT_COPY, ("notice.copy_unreadable",))
    _CACHE["key"] = key
    _CACHE["loaded"] = loaded
    return loaded


def catalog() -> dict:
    """Every notice this dashboard can show, with the overlay applied."""
    return _load()[0]


def overlay_problems() -> tuple:
    """Codes to raise because the overlay itself could not be used."""
    return _load()[1]


def get(code: str) -> Notice:
    """The entry for `code`, falling back to the plain one."""
    return catalog().get(code) or catalog()[FALLBACK_CODE]


def label(code: str) -> str:
    """The 2-4 word name for chips, pills and tooltips."""
    return get(code).label


def is_permanent(code: str) -> bool:
    return code in _PERMANENT


# ─── classification ────────────────────────────────────────────────────

_BY_KIND = {
    "RegenTimeout": "rebuild.timeout",
    "OutputRejected": "rebuild.bad_output",
    "FragmentRejected": "rebuild.bad_output",
    "AgentOutputError": "rebuild.bad_output",
    "SessionGone": "rebuild.chat_vanished",
    "CliMissing": "account.cli_missing",
    "ProbeTimeout": "account.check_unclear",
}

# Order decides the headline when a message carries several markers: an empty
# balance and a model refusal both carry a status code the sign-in rule claims.
_MARKERS = (
    (("claude cli not found", "no such file or directory", "errno 2",
      "command not found"), "account.cli_missing"),
    (("credit balance", "insufficient credit"), "account.no_credit"),
    (("usage limit", "quota", "rate limit", "429"), "account.usage_limit"),
    (("does not have access", "model not found"), "account.model_denied"),
    (("401", "403", "oauth", "re-authenticate", "authentication", "authenticate",
      "invalid api key", "not logged in", "please run /login"), "account.signed_out"),
    (("prompt is too long",), "rebuild.too_large"),
)


def classify(kind: str, message: str) -> str:
    """The notice code for a raw failure."""
    kind = kind or ""
    lowered = (message or "").lower()
    if kind in _BY_KIND:
        return _BY_KIND[kind]
    for markers, code in _MARKERS:
        if any(m in lowered for m in markers):
            return code
    return "account.check_unclear" if kind == "AuthProbe" else FALLBACK_CODE


def from_probe(ok: bool, kind: str, detail: str) -> "str | None":
    """The code a startup probe result raises, or None when it is healthy."""
    if ok:
        return None
    return classify(kind or "AuthProbe", detail)


# ─── diagnostics: numbers that describe a failure, not a conversation ──

def _command(label_text: str, value: str) -> dict:
    return {"label": label_text, "kind": "command", "value": value}


def _link(label_text: str, value: str) -> dict:
    return {"label": label_text, "kind": "link", "value": value}


def _copy(label_text: str, value: str) -> dict:
    return {"label": label_text, "kind": "copy", "value": value}


def report_actions(summary: str) -> list:
    """A pre-filled new-issue link plus a copy of it, for a browser pane that is
    not signed in to GitHub."""
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


# The project hash stays out: it is a slug of the filesystem path and would put
# the person's username and directory layout into a public issue.
SAFE_MEASUREMENTS = (
    ("model", "Model"),
    ("prompt_words", "Prompt size (words)"),
    ("input_tokens", "Input tokens"),
    ("output_tokens", "Output tokens"),
    ("output_bytes", "Output (bytes)"),
    ("wall_ms", "Wall time (ms)"),
    ("attempts", "Attempts"),
)


def diagnostics(code: str, measurements: dict, timeout_s=None) -> list:
    """A metadata-only picture of a failure, safe to paste in public."""
    row = measurements or {}
    items = [{"label": "Plugin", "value": PLUGIN},
             {"label": "Failure", "value": code or "unknown"}]
    when = row.get("ts")
    if when:
        items.append({"label": "When (UTC)",
                      "value": datetime.fromtimestamp(when, timezone.utc)
                                       .strftime("%Y-%m-%d %H:%M:%S")})
    if timeout_s:
        items.append({"label": "Time limit (s)", "value": int(timeout_s)})
    for field, label_text in SAFE_MEASUREMENTS:
        value = row.get(field)
        if value not in (None, ""):
            items.append({"label": label_text, "value": value})
    return items


def diagnostics_text(items: list) -> str:
    return "\n".join(f"{item['label']}: {item['value']}" for item in items)


# ─── filling in this chat's numbers ────────────────────────────────────

def _readable(value) -> str:
    if isinstance(value, float):
        return f"{value:.0f}"
    return str(value)


def _fill(text: str, facts: dict) -> str:
    """Substitute {name} from `facts`, dropping any sentence whose value is
    missing rather than printing a hole or a None."""
    if not text or "{" not in text:
        return text
    kept = []
    for sentence in re.split(r"(?<=\.) ", text):
        names = _PLACEHOLDER_RE.findall(sentence)
        if any(facts.get(n) is None for n in names):
            continue
        kept.append(_PLACEHOLDER_RE.sub(
            lambda m: _readable(facts[m.group(1)]), sentence))
    return " ".join(kept)


def _step_dict(step: Step, facts: dict) -> dict:
    return {"text": _fill(step.text, facts), "command": step.command,
            "href": step.href, "hrefLabel": step.href_label}


def envelope(code: str, *, facts=None, detail: str = "", measurements=None,
             timeout_s=None, id: str = "", at: int = 0, acked_at=None,
             resolved_at=None, project: str = "", session: str = "") -> dict:
    """One notice as the renderer and the browser consume it."""
    n = get(code)
    facts = facts or {}
    diag = diagnostics(n.code, measurements or {}, timeout_s)
    actions = []
    if n.report:
        actions = report_actions(_fill(n.title, facts) or n.label)
        actions.append(_copy("Copy diagnostics", diagnostics_text(diag)))
    return {
        "code": n.code,
        "severity": n.severity,
        "scope": n.scope,
        "id": id or f"{n.scope}:{n.code}",
        "title": _fill(n.title, facts),
        "what": _fill(n.what, facts),
        "label": n.label,
        "steps": [_step_dict(s, facts) for s in n.steps],
        "explain": n.explain,
        "detail": detail,
        "diagnostics": diag,
        "actions": actions,
        "dismiss": n.dismiss,
        "selfHeals": n.self_heals,
        "at": at,
        "project": project,
        "session": session,
        "ackedAt": acked_at,
        "resolvedAt": resolved_at,
    }
