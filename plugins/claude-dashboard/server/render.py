"""Render a DashboardModel to an HTML body fragment. Deterministic and pure.

Emits the class contract dashboard.css/dashboard.js expect (watch-deck ack
buttons, todo-list, timeline). Text fields and freeform bodies are inlined raw
(they may carry inline HTML). Journey marks its last beat `current`; heads-up
and to-do render all rows — done to-dos are permanent history the JS folds.
"""
import re
from html import escape, unescape

from models import DashboardModel, HeadsupItem, TodoStatus

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


def _blocks(m: DashboardModel, fallback_title: str = "",
            journey: bool = True) -> "list[tuple[str, str]]":
    """Ordered (card, html) for every card; freeform collapsed into one entry, journey last."""
    blocks = [
        ("header", _header(m, fallback_title)),
        ("links", _links(m)),
        ("cta", _cta(m)),
        ("todo", _todo(m)),
        ("headsup", _headsup(m)),
        ("freeform", "\n".join(h for h in _freeform(m) if h)),
    ]
    if journey:
        blocks.append(("journey", _journey(m)))
    return blocks


def render(m: DashboardModel, fallback_title: str = "", journey: bool = True) -> str:
    """`fallback_title` fills the header when the model has not set a title."""
    return "\n".join(html for _, html in _blocks(m, fallback_title, journey) if html)


def block_sizes(m: DashboardModel) -> "dict[str, int]":
    """Rendered UTF-8 byte size of each card; absent cards are 0."""
    return {name: len(html.encode("utf-8")) for name, html in _blocks(m)}


def _abs_turn(m: DashboardModel, turn: int) -> int:
    return m.turn_base + turn


def _age(m: DashboardModel, stamps: "list[tuple[str, int]]", prefix: str = "") -> str:
    """Right-edge age cell: the newest stamp in turns, exact turns on hover."""
    known = [(label, t) for label, t in stamps if t]
    if not known:
        return ""
    now = _abs_turn(m, m.turn)
    ago = max(0, now - _abs_turn(m, known[-1][1]))
    detail = " · ".join(f"{lab} turn {_abs_turn(m, t)}" for lab, t in known)
    unit = "turn" if ago == 1 else "turns"
    text = "this turn" if ago == 0 else f"{prefix}{ago} {unit} ago"
    return f'<span class="age" title="{detail} · now turn {now}">{text}</span>'


def _meta_strip(m: DashboardModel) -> str:
    """The quiet state line above the title: short metadata only — phase,
    turn, and the slot the server fills with this chat's lineage."""
    phase_cls, phase_label = _PHASE_CHIP[m.phase.value]
    bits = [f'<span class="phase-chip {phase_cls}">{phase_label}</span>',
            f'<span class="meta-turn">turn {_abs_turn(m, m.turn)}</span>']
    bits.append('<span class="meta-lineage"></span>')
    return '  <div class="meta-strip">' + "".join(bits) + "</div>"


def _header(m: DashboardModel, fallback_title: str = "") -> str:
    title = m.title or fallback_title or "Session"
    lines = ['<header class="session-header">', _meta_strip(m), f"  <h1>{title}</h1>"]
    description = m.tldr.essence or m.tldr.status
    if description:
        lines.append(f'  <p class="essence">{description}</p>')
    lines.append("</header>")
    return "\n".join(lines)


# The CTA number marker rots one visible step per turn of age, saturating
# at CTA_AGE_MAX; the tooltip keeps the true count.
CTA_AGE_MAX = 6

_TRASH_SVG = ('<svg viewBox="0 0 24 24" width="14" height="14" fill="none" '
              'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
              'aria-hidden="true"><path d="M4 7h16M10 11v6M14 11v6'
              'M6 7l1 13h10l1-13M9 7V4h6v3"/></svg>')

def _trash_btn(verdict: str, label: str, title: str) -> str:
    return (f'<button class="verdict-btn trash" data-verdict="{verdict}" '
            f'type="button" aria-label="{label}" title="{title}">{_TRASH_SVG}</button>')


_DISMISS_BTN = _trash_btn("dismissed", "dismiss", "dismiss")
_DROP_BTN = _trash_btn("dropped", "drop", "drop (no longer relevant)")
_CHECK_BTN = ('<button class="todo-check" data-verdict="done" type="button" '
              'aria-label="mark done" title="mark done"></button>')


def _cta_age_class(age: int) -> str:
    return f"age-{min(max(age, 0), CTA_AGE_MAX)}"


_LINK_ICON = {"issue": "🎫", "pr": "🔀", "branch": "🌿", "doc": "📄"}


def _links(m: DashboardModel) -> str:
    if not m.links:
        return ""
    chips = []
    for link in m.links:
        icon = _LINK_ICON.get(link.kind, "🔗")
        kind = f'<span class="kind">{link.kind}</span> ' if link.kind else ""
        inner = f"{icon} {kind}{link.label}"
        if link.url:
            href = link.url.replace('"', "&quot;")
            chips.append(f'  <a class="link-chip" href="{href}">{inner}</a>')
        else:
            chips.append(f'  <span class="link-chip">{inner}</span>')
    return '<div class="link-chips">\n' + "\n".join(chips) + "\n</div>"


def _cta(m: DashboardModel) -> str:
    lines = ['<section class="card questions">', "  <h2>📌 Call to action</h2>"]
    if m.last_turn.bullets:
        lines.append('  <div class="last-turn-label">Last turn'
                     f'<span class="last-turn-turn">· turn {_abs_turn(m, m.last_turn.turn)}</span></div>')
        lines.append('  <ul class="last-turn">')
        for bullet in m.last_turn.bullets:
            lines.append(f"    <li>{bullet}</li>")
        lines.append("  </ul>")
        lines.append('  <div class="last-turn-divider"></div>')
    if m.cta:
        lines.append('  <ol class="questions-list">')
        for c in m.cta:
            age = max(0, m.turn - c.created_turn)
            unit = "turn" if age == 1 else "turns"
            lines.append(
                f'    <li class="{_cta_age_class(age)}" data-item-id="{c.id}" '
                f'title="waiting {age} {unit}">'
                f'<span class="label">{c.text}</span>{_DISMISS_BTN}</li>'
            )
        lines.append("  </ol>")
    else:
        lines.append('  <div class="all-clear">✓ Nothing pending</div>')
    lines.append("</section>")
    return "\n".join(lines)


def _todo(m: DashboardModel) -> str:
    if not m.todo:
        return ""
    lines = ['<section class="card todo">', "  <h2>📋 To-do</h2>", '  <ul class="todo-list">']
    for t in m.todo:
        age = _age(m, [("created", t.created_turn), ("done", t.done_turn)],
                   prefix="done " if t.done_turn else "")
        if t.status == TodoStatus.done:
            lines.append(f'    <li class="done"><span class="label">{t.text}</span>{age}</li>')
            continue
        # .checkable suppresses the ::before status marker (CSS); blocked rows keep ✗.
        checkable = t.status != TodoStatus.blocked
        cls = t.status.value + (" checkable" if checkable else "")
        check = _CHECK_BTN if checkable else ""
        lines.append(
            f'    <li class="{cls}" data-item-id="{t.id}">'
            f'{check}<span class="label">{t.text}</span>{_DROP_BTN}{age}</li>'
        )
    lines += ["  </ul>", "</section>"]
    return "\n".join(lines)


def _sentence(s: str) -> str:
    return s if s.endswith((".", "!", "?", "…", ":", ";")) else s + "."


def _copy_text(m: DashboardModel, h: HeadsupItem) -> str:
    """The row as one plain-text line the user pastes into the chat as-is:
    provenance prefix, then the fields verbatim, no action words."""
    stamp = f", raised turn {_abs_turn(m, h.created_turn)}" if h.created_turn else ""
    line = (f"Dashboard heads-up ({h.sev.value}{stamp}): "
            f"{_sentence(unescape(_plain(h.what)))} "
            f"Why: {_sentence(unescape(_plain(h.why)))}")
    if h.where:
        line += f" Where: {unescape(_plain(h.where))}"
    return line


def _headsup(m: DashboardModel) -> str:
    lines = ['<section class="card heads-up">', "  <h2>🚨 Heads-up</h2>"]
    if m.headsup:
        lines += [
            '  <table class="watch-deck">',
            '    <thead><tr><th class="sev-col">Sev</th><th>Easy to miss</th>'
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
                f'        <td class="ack-col">'
                f'{_age(m, [("raised", h.created_turn)])}'
                '<button class="ack-btn" type="button">acknowledge</button>'
                f'<button class="copy-btn" type="button" title="copy for the agent" '
                f'data-copy="{escape(_copy_text(m, h))}">copy</button></td>',
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


_FF_DISMISS_BTN = ('<button class="ff-dismiss" data-verdict="dismissed" '
                   'type="button" aria-label="dismiss" title="dismiss">✕</button>')


def _freeform(m: DashboardModel) -> "list[str]":
    # Each body is a full <section> card, emitted verbatim inside a thin
    # wrapper that carries the dismiss chrome and the slot id.
    out = []
    for f in m.freeform:
        dismissed = " dismissed" if f.dismissed_turn else ""
        age = _age(m, [("updated", f.changed_turn)])
        out.append(f'<div class="freeform-slot{dismissed}" data-item-id="{f.id}">'
                   f'{age}{_FF_DISMISS_BTN}{f.html}</div>')
    return out
