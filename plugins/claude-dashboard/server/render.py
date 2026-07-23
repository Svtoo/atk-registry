"""Render a DashboardModel to an HTML body fragment. Deterministic and pure.

Emits the class contract dashboard.css/dashboard.js expect (watch-deck ack
buttons, todo-list, timeline). Text fields and freeform bodies are inlined raw
(they may carry inline HTML). To-do folds runs of DONE_FOLD_RUN+ done items into
one line; journey marks its last beat `current`; heads-up renders all rows.
"""
import re

from models import DONE_FOLD_RUN, DashboardModel, TodoStatus

_PHASE_CHIP = {
    "planning": ("info", "Planning"),
    "building": ("ok", "Building"),
    "blocked": ("bad", "Blocked"),
    "review": ("warn", "Awaiting review"),
    "shipped": ("ok", "Shipped"),
}
_BADGE = {"user": "👤", "agent": "🤖", "joint": "🤝"}
_WHO = {"user": "You", "agent": "Agent", "joint": "You + Agent"}

_TAG = re.compile(r"<[^>]+>")


def _plain(s: str) -> str:
    """Strip inline HTML."""
    return _TAG.sub("", s).strip()


def _blocks(m: DashboardModel, fallback_title: str = "") -> "list[tuple[str, str]]":
    """Ordered (card, html) for every card; freeform collapsed into one entry, journey last."""
    return [
        ("header", _header(m, fallback_title)),
        ("cta", _cta(m)),
        ("todo", _todo(m)),
        ("headsup", _headsup(m)),
        ("freeform", "\n".join(h for h in _freeform(m) if h)),
        ("journey", _journey(m)),
    ]


def render(m: DashboardModel, fallback_title: str = "") -> str:
    """`fallback_title` fills the header when the model has not set a title."""
    return "\n".join(html for _, html in _blocks(m, fallback_title) if html)


def block_sizes(m: DashboardModel) -> "dict[str, int]":
    """Rendered UTF-8 byte size of each card; absent cards are 0."""
    return {name: len(html.encode("utf-8")) for name, html in _blocks(m)}


def _glance_row(key: str, val: str, extra: str = "") -> "list[str]":
    cls = "glance-row" + (f" {extra}" if extra else "")
    return [f'    <div class="{cls}">', f"      <dt>{key}</dt>", f"      <dd>{val}</dd>", "    </div>"]


def _header(m: DashboardModel, fallback_title: str = "") -> str:
    # Glance grid: what / where / your move. Values from tldr; labels + phase chip owned here.
    phase_cls, phase_label = _PHASE_CHIP[m.phase.value]
    where = f'<span class="phase-chip {phase_cls}">{phase_label}</span>'
    if m.tldr.status:
        where += f" {m.tldr.status}"

    title = m.title or fallback_title or "Session"
    lines = ['<header class="session-header">', f"  <h1>{title}</h1>", '  <dl class="glance">']
    lines += _glance_row("what", m.tldr.essence or "—")
    lines += _glance_row("where", where)
    if m.tldr.next:
        lines += _glance_row("your move", m.tldr.next, extra="move")
    else:
        lines += _glance_row("your move", "Nothing pending right now.", extra="move clear")
    lines += ["  </dl>", "</header>"]
    return "\n".join(lines)


def _cta(m: DashboardModel) -> str:
    lines = ['<section class="card questions">', "  <h2>📌 Call to action</h2>"]
    if m.cta:
        lines.append('  <ol class="questions-list">')
        for c in m.cta:
            lines.append(f'    <li><span class="label">{c.text}</span></li>')
        lines.append("  </ol>")
    else:
        lines.append('  <div class="all-clear">✓ Nothing pending</div>')
    lines.append("</section>")
    return "\n".join(lines)


def _todo(m: DashboardModel) -> str:
    if not m.todo:
        return ""
    lines = ['<section class="card todo">', "  <h2>📋 To-do</h2>", '  <ul class="todo-list">']
    items, i, n = m.todo, 0, len(m.todo)
    while i < n:
        if items[i].status == TodoStatus.done:
            j = i
            while j < n and items[j].status == TodoStatus.done:
                j += 1
            run = items[i:j]
            if len(run) >= DONE_FOLD_RUN:
                label = f"{len(run)} done — {_plain(run[0].text)} … {_plain(run[-1].text)}"
                lines.append(f'    <li class="done"><span class="label">{label[:200]}</span></li>')
            else:
                for t in run:
                    lines.append(f'    <li class="done"><span class="label">{t.text}</span></li>')
            i = j
        else:
            t = items[i]
            lines.append(f'    <li class="{t.status.value}"><span class="label">{t.text}</span></li>')
            i += 1
    lines += ["  </ul>", "</section>"]
    return "\n".join(lines)


def _headsup(m: DashboardModel) -> str:
    lines = ['<section class="card heads-up">', "  <h2>🚨 Heads-up</h2>"]
    if m.headsup:
        lines += [
            '  <table class="watch-deck">',
            '    <thead><tr><th class="sev-col">Sev</th><th>What I did / found</th>'
            '<th>Why it might bite</th><th>Where to check</th><th class="ack-col">Acknowledge</th></tr></thead>',
            "    <tbody>",
        ]
        for h in reversed(m.headsup):  # newest-first; JS reorders acked to the bottom
            lines += [
                f'      <tr data-row-id="{h.id}">',
                f'        <td class="sev-col"><span class="{h.sev.value}">{h.sev.value}</span></td>',
                f"        <td>{h.what}</td>",
                f"        <td>{h.why}</td>",
                f"        <td>{h.where}</td>",
                '        <td class="ack-col"><button class="ack-btn" type="button">acknowledge</button></td>',
                "      </tr>",
            ]
        lines += ["    </tbody>", "  </table>"]
    else:
        lines.append('  <div class="all-clear">✓ Nothing surfaced this session</div>')
    lines.append("</section>")
    return "\n".join(lines)


def _journey(m: DashboardModel) -> str:
    if not m.journey:
        return ""
    lines = ['<section class="card journey">', "  <h2>🗺️ Journey · 🎯 Decisions</h2>", '  <ol class="timeline">']
    last = len(m.journey) - 1
    for i, j in enumerate(m.journey):
        current = i == last
        badge_cls = "here" if current else j.kind.value
        emoji = "📍" if current else _BADGE[j.kind.value]
        lines += [
            '    <li class="current">' if current else "    <li>",
            f'      <span class="badge {badge_cls}">{emoji}</span>',
            f'      <div class="what"><span class="who-name">{_WHO[j.kind.value]}</span> — {j.what}</div>',
            f'      <div class="why">{j.why}</div>',
            "    </li>",
        ]
    lines += ["  </ol>", "</section>"]
    return "\n".join(lines)


def _freeform(m: DashboardModel) -> "list[str]":
    # Each body is a full <section> card, emitted verbatim.
    return [f.html for f in m.freeform]
