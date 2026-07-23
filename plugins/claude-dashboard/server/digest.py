"""Digest: render the server-owned model as a compact, agent-facing view for
the next regen.

This is what the agent SEES each turn — the current dashboard as structured
state with change-log motion — so it emits a small delta instead of rewriting
everything.

  - Heads-up is shown in FULL (every row) so the agent never re-raises a
    near-duplicate: the user's attention is the scarce resource, not agent tokens.
  - Freeform BODIES are shown IN FULL. Freeform is the sticky reference layer:
    the agent must see the current body to know it is still correct and LEAVE IT
    ALONE (the anti-churn win), and to edit it faithfully when the design does
    change. Bodies are small and change rarely, so the prompt cost is bounded.
  - Every mutable item shows "changed N turns ago: reason" so the agent sees
    trajectory and decides what actually needs touching.
"""
from models import JOURNEY_MAX, DashboardModel


def _ago(current_turn: int, when: int) -> str:
    delta = current_turn - when
    return "now" if delta <= 0 else f"{delta}t ago"


def build_digest(m: DashboardModel, now_turn: "int | None" = None) -> str:
    """Render the model for the agent. `now_turn` is the current conversation
    turn; "changed Nt ago" is measured against it (regens can skip turns, so
    the state's own turn may lag). Defaults to the state's turn."""
    now = m.turn if now_turn is None else now_turn
    L = [
        f"# Dashboard state — as of conversation turn {m.turn}",
        f"title: {m.title or '(none yet)'}",
        f"phase: {m.phase.value}",
        f"tldr.essence (the what): {m.tldr.essence or '(none)'}",
        f"tldr.status (the where): {m.tldr.status or '(none)'}",
        f"tldr.next (your move): {m.tldr.next or '(none)'}",
        "",
        f"## CTA ({len(m.cta)}) — blockers/questions for the user; remove on resolve",
    ]
    for c in m.cta:
        L.append(f"- {c.id} [{_ago(now, c.changed_turn)}: {c.reason}] {c.text}")

    L += ["", f"## To-do ({len(m.todo)})"]
    for t in m.todo:
        L.append(f"- {t.id} {t.status.value} [{_ago(now, t.changed_turn)}: {t.reason}] {t.text}")

    L += ["", f"## Heads-up ({len(m.headsup)}) — FULL list; update rows by id as facts change; never add a duplicate row"]
    for h in m.headsup:
        L.append(
            f"- {h.id} {h.sev.value} [{_ago(now, h.changed_turn)}: {h.reason}] "
            f"what={h.what} | why={h.why} | where={h.where}"
        )

    over_cap = (
        f" — ⚠ OVER CAP ({len(m.journey)} > {JOURNEY_MAX}): this turn emit ONE journey.fold "
        f"whose `what` summarizes the oldest beats (the server keeps the most recent {JOURNEY_MAX - 1})"
        if len(m.journey) > JOURNEY_MAX else ""
    )
    L += ["", f"## Journey ({len(m.journey)}){over_cap}"]
    for j in m.journey:
        L.append(f"- {j.id} {j.kind.value} (turn {j.turn}) what={j.what} | why={j.why}")

    L += ["", f"## Freeform ({len(m.freeform)}) — sticky reference cards, shown in full; "
              "re-upsert a card by id ONLY when the design it shows actually changed, "
              "and then change the minimum"]
    for f in m.freeform:
        L.append(f"- {f.id} [{_ago(now, f.changed_turn)}: {f.reason}]")
        L.append(f.html)
    L.append("")
    return "\n".join(L)
