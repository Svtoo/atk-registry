"""Fold: apply an agent `Update` onto the server-owned DashboardModel.
Pure; the input model is never mutated."""
import hashlib

from models import (
    JOURNEY_MAX,
    CtaItem,
    DashboardModel,
    FreeformSlot,
    HeadsupItem,
    JourneyItem,
    JourneyKind,
    TodoItem,
    TodoStatus,
    Update,
)


def _hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]


def _find(items, item_id):
    for it in items:
        if it.id == item_id:
            return it
    return None


def apply_ops(model: DashboardModel, update: Update, bodies: dict, turn: int) -> DashboardModel:
    """Fold one turn's `update` into `model`, returning a new model.

    `turn` is the ABSOLUTE conversation turn (how deep the chat is), passed in by
    the caller from the transcript. It stamps every created/updated item and every
    journey beat, so `changed_turn` reflects real conversation recency and the
    timeline carries real turn numbers — not an internal regen counter.

    `bodies` maps each freeform `htmlRef` to its raw HTML (from the side-channel).
    An op that targets a nonexistent id is skipped, never invented — a stale
    reference must not corrupt the model.
    """
    m = model.model_copy(deep=True)

    if update.phase is not None:
        m.phase = update.phase
    if update.title is not None:
        m.title = update.title
    if update.tldr is not None:
        # Diff semantics: only the fields the agent sent change; an omitted
        # field keeps its line, an explicit empty string clears it.
        for line in ("essence", "status", "next"):
            value = getattr(update.tldr, line)
            if value is not None:
                setattr(m.tldr, line, value)

    def mint(prefix: str) -> str:
        m.seq += 1
        return f"{prefix}{m.seq}"

    for op in update.ops:
        kind = op.op

        if kind == "todo.upsert":
            if op.id is None:
                m.todo.append(TodoItem(
                    id=mint("t"), text=op.text or "",
                    status=op.status or TodoStatus.open,
                    order=m.seq, changed_turn=turn, reason=op.reason,
                ))
            else:
                it = _find(m.todo, op.id)
                if it is None:
                    continue
                if op.text is not None:
                    it.text = op.text
                if op.status is not None:
                    it.status = op.status
                it.changed_turn = turn
                if op.reason:  # an omitted reason keeps the stored one (digest motion)
                    it.reason = op.reason

        elif kind == "todo.remove":
            m.todo = [t for t in m.todo if t.id != op.id]

        elif kind == "cta.upsert":
            if op.id is None:
                m.cta.append(CtaItem(
                    id=mint("c"), text=op.text or "",
                    order=m.seq, changed_turn=turn, reason=op.reason,
                ))
            else:
                it = _find(m.cta, op.id)
                if it is None:
                    continue
                if op.text is not None:
                    it.text = op.text
                it.changed_turn = turn
                if op.reason:
                    it.reason = op.reason

        elif kind == "cta.remove":
            m.cta = [c for c in m.cta if c.id != op.id]

        elif kind == "headsup.upsert":
            if op.id is None:
                m.headsup.append(HeadsupItem(
                    id=mint("h"), sev=op.sev, what=op.what or "",
                    why=op.why or "", where=op.where or "",
                    order=m.seq, changed_turn=turn, reason=op.reason,
                ))
            else:
                it = _find(m.headsup, op.id)
                if it is None:
                    continue
                if op.sev is not None:
                    it.sev = op.sev
                if op.what is not None:
                    it.what = op.what
                if op.why is not None:
                    it.why = op.why
                if op.where is not None:
                    it.where = op.where
                it.changed_turn = turn
                if op.reason:
                    it.reason = op.reason

        elif kind == "journey.add":
            m.journey.append(JourneyItem(
                id=mint("j"), kind=op.kind, what=op.what, why=op.why, turn=turn,
            ))

        elif kind == "journey.update":
            it = _find(m.journey, op.id)
            if it is not None:  # the beat keeps its original turn stamp
                if op.what is not None:
                    it.what = op.what
                if op.why is not None:
                    it.why = op.why

        elif kind == "journey.fold":
            # Agent-driven compression: replace the oldest beats with the agent's
            # one-line summary, keeping the most recent JOURNEY_MAX-1 verbatim. The
            # server only prompts this (via the digest); the agent authors the story.
            cutoff = max(JOURNEY_MAX - 1, 0)
            if len(m.journey) > cutoff:
                keep = m.journey[-cutoff:] if cutoff else []
                m.journey = [JourneyItem(
                    id=mint("j"), kind=JourneyKind.joint,
                    what=op.what, why=op.why, turn=turn,
                )] + keep

        elif kind == "freeform.upsert":
            if op.html_ref not in bodies:
                continue  # parse_output guarantees this, but stay defensive
            body = bodies[op.html_ref]
            h = _hash(body)
            if op.id is None:
                m.freeform.append(FreeformSlot(
                    id=mint("f"), html=body, hash=h,
                    changed_turn=turn, reason=op.reason,
                ))
            else:
                it = _find(m.freeform, op.id)
                if it is None:
                    continue
                if it.hash != h:  # an identical body is not a change (dedup)
                    it.html = body
                    it.hash = h
                    it.changed_turn = turn
                    if op.reason:
                        it.reason = op.reason

        elif kind == "freeform.remove":
            m.freeform = [f for f in m.freeform if f.id != op.id]

    m.turn = turn
    return m
