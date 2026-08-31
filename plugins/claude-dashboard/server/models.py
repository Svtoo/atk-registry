"""The server-owned dashboard model and the agent op-set schema.

The server owns the dashboard as this typed state. Each turn the agent emits an
`Update` (a delta) validated against this schema. Freeform HTML bodies travel in
a fenced side-channel and are attached to `freeform.upsert` ops by reference
(`htmlRef`); see agent_io.parse_output.

Op field descriptions are load-bearing: `prompt.assemble_prompt` renders this
schema into the agent's instructions, so a `Field(description=...)` IS the
guidance the agent sees.
"""
from enum import Enum
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

SHORT = 400        # a short prose field
# Past ~50k chars a single freeform body alone approaches the regen wall-clock
# timeout; parse_output rejects the body and feeds the limit back to the agent.
HTML_MAX = 50000

JOURNEY_MAX = 5        # total timeline rows, including the fold summary


class Phase(str, Enum):
    planning = "planning"
    building = "building"
    blocked = "blocked"
    review = "review"
    shipped = "shipped"


class TodoStatus(str, Enum):
    open = "open"
    active = "active"
    done = "done"
    blocked = "blocked"


class Sev(str, Enum):
    risk = "risk"
    flag = "flag"
    note = "note"    # historic rows only; the op schema (OpSev) cannot raise it


class OpSev(str, Enum):
    risk = "risk"
    flag = "flag"


class JourneyKind(str, Enum):
    user = "user"
    agent = "agent"
    joint = "joint"


class _Base(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class _OpBase(_Base):
    # extra="forbid": a wrong field name fails validation loudly instead of
    # silently validating as an empty patch.
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


# ── Server state (owned + rendered by the server) ──────────────────────

class TodoItem(_Base):
    id: str
    text: str = Field(max_length=SHORT)
    status: TodoStatus
    order: int = 0
    created_turn: int = 0    # 0 = unknown (item predates turn stamping)
    changed_turn: int = 0
    done_turn: int = 0       # 0 = not done, or done before turn stamping
    reason: str = Field("", max_length=SHORT)


class LinkItem(_Base):
    id: str
    label: str = Field(max_length=SHORT)
    url: str = Field("", max_length=SHORT)    # empty: a plain reference, e.g. a branch name
    kind: str = Field("", max_length=40)      # short type tag: issue | pr | branch | doc | …
    order: int = 0
    changed_turn: int = 0
    reason: str = Field("", max_length=SHORT)


class CtaItem(_Base):
    id: str
    text: str = Field(max_length=SHORT)
    order: int = 0
    changed_turn: int = 0
    # Server-stamped at creation; drives the age display. 0 = unknown age.
    created_turn: int = 0
    reason: str = Field("", max_length=SHORT)


class HeadsupItem(_Base):
    id: str
    sev: Sev
    what: str = Field(max_length=SHORT)
    why: str = Field(max_length=SHORT)
    where: str = Field("", max_length=SHORT)
    order: int = 0
    created_turn: int = 0    # 0 = unknown (item predates turn stamping)
    changed_turn: int = 0
    reason: str = Field("", max_length=SHORT)


class JourneyItem(_Base):
    id: str
    kind: JourneyKind
    what: str = Field(max_length=SHORT)
    why: str = Field(max_length=SHORT)
    turn: int = 0


class FreeformSlot(_Base):
    id: str
    html: str = Field(max_length=HTML_MAX)
    hash: str = ""
    changed_turn: int = 0
    dismissed_turn: int = 0  # server-stamped from the user's dismiss; 0 = live
    reason: str = Field("", max_length=SHORT)


class Tldr(_Base):
    # The glance's two lines: what / where.
    essence: str = Field("", max_length=SHORT)
    status: str = Field("", max_length=SHORT)


class LastTurn(_Base):
    bullets: "list[str]" = Field(default_factory=list)
    turn: int = 0    # conversation turn the bullets describe (server-stamped)


class TldrPatch(_OpBase):
    essence: Optional[str] = Field(None, max_length=SHORT, description="the 'what' — one line on what this chat is really about; omit to keep the current line")
    status: Optional[str] = Field(None, max_length=SHORT, description="the 'where' — one line on where things stand (renders beside the phase chip); omit to keep")


class DashboardModel(_Base):
    title: str = Field("", max_length=SHORT)
    phase: Phase = Phase.planning
    turn: int = 0
    turn_base: int = 0   # turns inherited from the chats this one continues
    seq: int = 0
    tldr: Tldr = Field(default_factory=Tldr)
    last_turn: LastTurn = Field(default_factory=LastTurn)
    links: list[LinkItem] = Field(default_factory=list)
    cta: list[CtaItem] = Field(default_factory=list)
    todo: list[TodoItem] = Field(default_factory=list)
    headsup: list[HeadsupItem] = Field(default_factory=list)
    journey: list[JourneyItem] = Field(default_factory=list)
    freeform: list[FreeformSlot] = Field(default_factory=list)


# ── Agent op-set (a delta) ─────────────────────────────────────────────

class TodoUpsert(_OpBase):
    op: Literal["todo.upsert"]
    id: Optional[str] = Field(None, description="existing task id from the digest; omit to create a new task")
    text: Optional[str] = Field(None, max_length=SHORT, description="task text; required when creating (no id)")
    status: Optional[TodoStatus] = Field(None, description="open | active | done | blocked")
    reason: str = Field("", max_length=SHORT, description="one-line motivation for this change (kept for future turns)")

    @model_validator(mode="after")
    def _create_requires_text(self):
        if self.id is None and not self.text:
            raise ValueError("todo.upsert without id (create) requires text")
        return self


class CtaUpsert(_OpBase):
    op: Literal["cta.upsert"]
    id: Optional[str] = Field(None, description="existing CTA id; omit to create a new one")
    text: Optional[str] = Field(None, max_length=SHORT, description="the blocker/question for the user; required when creating")
    reason: str = Field("", max_length=SHORT, description="one-line motivation for this change")

    @model_validator(mode="after")
    def _create_requires_text(self):
        if self.id is None and not self.text:
            raise ValueError("cta.upsert without id (create) requires text")
        return self


class CtaRemove(_OpBase):
    op: Literal["cta.remove"]
    id: str = Field(description="id of the resolved CTA to remove")
    reason: str = Field("", max_length=SHORT, description="one-line motivation")


class LinkUpsert(_OpBase):
    op: Literal["link.upsert"]
    id: Optional[str] = Field(None, description="existing link id; omit to create a new one")
    label: Optional[str] = Field(None, max_length=SHORT, description="display text; required when creating")
    url: Optional[str] = Field(None, max_length=SHORT, description="destination; empty string for a plain reference such as a branch name")
    kind: Optional[str] = Field(None, max_length=40, description="short type tag shown on the chip: issue | pr | branch | doc | …")
    reason: str = Field("", max_length=SHORT, description="one-line motivation for this change")

    @model_validator(mode="after")
    def _create_requires_label(self):
        if self.id is None and not self.label:
            raise ValueError("link.upsert without id (create) requires label")
        return self


class LinkRemove(_OpBase):
    op: Literal["link.remove"]
    id: str = Field(description="id of the link that stopped mattering")
    reason: str = Field("", max_length=SHORT, description="one-line motivation")


class LastTurnSet(_OpBase):
    op: Literal["last_turn.set"]
    bullets: list[Annotated[str, Field(max_length=SHORT)]] = Field(
        min_length=1, max_length=3,
        description="1-3 short outcome bullets for the newest turn only; replaces the previous set wholesale")


class HeadsupUpsert(_OpBase):
    op: Literal["headsup.upsert"]
    id: Optional[str] = Field(None, description="existing row id; omit to create a new one")
    sev: Optional[OpSev] = Field(None, description="risk | flag; required when creating")
    what: Optional[str] = Field(None, max_length=SHORT, description="the thing the user likely missed; required when creating")
    why: Optional[str] = Field(None, max_length=SHORT, description="why it might bite; required when creating")
    where: Optional[str] = Field(None, max_length=SHORT, description="where to check")
    reason: str = Field("", max_length=SHORT, description="one-line motivation for this change")

    @model_validator(mode="after")
    def _create_requires_fields(self):
        if self.id is None and not (self.sev and self.what and self.why):
            raise ValueError("headsup.upsert without id (create) requires sev, what, why")
        return self


# A heads-up row is a permanent record: there is no remove op, and acknowledged
# rows fold in the frontend rather than being deleted.


class JourneyAdd(_OpBase):
    op: Literal["journey.add"]
    kind: JourneyKind = Field(description="user | agent | joint — who drove this beat")
    what: str = Field(max_length=SHORT, description="the load-bearing decision or inflection point")
    why: str = Field(max_length=SHORT, description="one-line rationale")


class JourneyUpdate(_OpBase):
    op: Literal["journey.update"]
    id: str = Field(description="existing beat id from the digest")
    what: Optional[str] = Field(None, max_length=SHORT, description="rewritten beat — one load-bearing decision or inflection point, no turn prefixes")
    why: Optional[str] = Field(None, max_length=SHORT, description="one-line rationale")


class JourneyFold(_OpBase):
    op: Literal["journey.fold"]
    what: str = Field(max_length=SHORT, description="the folded span distilled to its one or two load-bearing outcomes — a beat, not an event inventory; emit only when the state says the journey is over its cap")
    why: str = Field("", max_length=SHORT, description="one-line rationale for the folded span")
    reason: str = Field("", max_length=SHORT, description="one-line motivation")


class FreeformUpsert(_OpBase):
    op: Literal["freeform.upsert"]
    id: Optional[str] = Field(None, description="existing slot id; omit to create a new visual")
    html_ref: str = Field(alias="htmlRef", description="ref of the <freeform ref=\"…\"> block carrying this slot's body — the FULL <section class=\"card free-form\">…</section>, rendered verbatim; style with the theme variables var(--fg), var(--muted), var(--accent), var(--card), var(--border), var(--ok), var(--warn), var(--bad) — never hardcoded colors")
    reason: str = Field("", max_length=SHORT, description="one-line motivation, e.g. what changed in the visual")


# Freeform has no remove op: dropping a whole card is the user's dismiss
# (a verdict), never the agent's call.


_OP_TYPES = (
    TodoUpsert,
    CtaUpsert, CtaRemove,
    LinkUpsert, LinkRemove,
    LastTurnSet,
    HeadsupUpsert,
    JourneyAdd, JourneyUpdate, JourneyFold,
    FreeformUpsert,
)
_JOURNEY_OP_TYPES = (JourneyAdd, JourneyUpdate, JourneyFold)

MAX_OPS = 40


def _make_update_model(op_types: "tuple[type, ...]") -> "type[_OpBase]":
    op_union = Annotated[Union[op_types], Field(discriminator="op")]

    class UpdateModel(_OpBase):
        """One turn's delta. Omitting an item keeps it; the server mints ids."""
        phase: Optional[Phase] = Field(None, description="set only when the phase changes")
        title: Optional[str] = Field(None, max_length=SHORT, description="set once at the start; rename rarely")
        tldr: Optional[TldrPatch] = Field(None, description="the glance lines; send only the fields that changed")
        ops: list[op_union] = Field(default_factory=list, max_length=MAX_OPS,
                                    description="the changes this turn; emit ONLY what materially changed, omit the rest")

    return UpdateModel


Update = _make_update_model(_OP_TYPES)
_UPDATE_WITHOUT_JOURNEY = _make_update_model(
    tuple(t for t in _OP_TYPES if t not in _JOURNEY_OP_TYPES))


def update_model(journey: bool = True) -> "type[Update]":
    """The op-set contract: with journey off, the journey ops are not part of
    it — they fail validation instead of being silently accepted."""
    return Update if journey else _UPDATE_WITHOUT_JOURNEY


def verdict_key(section: str, item_id: str) -> str:
    return f"{section}:{item_id}"


def split_verdict_key(key: str) -> "tuple[str, str]":
    section, _, item_id = key.partition(":")
    return section, item_id
