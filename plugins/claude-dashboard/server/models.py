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
DONE_FOLD_RUN = 3      # consecutive done to-dos that fold into one line at render


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
    note = "note"


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
    changed_turn: int = 0
    reason: str = Field("", max_length=SHORT)


class CtaItem(_Base):
    id: str
    text: str = Field(max_length=SHORT)
    order: int = 0
    changed_turn: int = 0
    reason: str = Field("", max_length=SHORT)


class HeadsupItem(_Base):
    id: str
    sev: Sev
    what: str = Field(max_length=SHORT)
    why: str = Field(max_length=SHORT)
    where: str = Field("", max_length=SHORT)
    order: int = 0
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
    reason: str = Field("", max_length=SHORT)


class Tldr(_Base):
    # The glance grid's three lines: what / where / your move.
    essence: str = Field("", max_length=SHORT)
    status: str = Field("", max_length=SHORT)
    next: str = Field("", max_length=SHORT)


class TldrPatch(_OpBase):
    essence: Optional[str] = Field(None, max_length=SHORT, description="the 'what' — one line on what this chat is really about; omit to keep the current line")
    status: Optional[str] = Field(None, max_length=SHORT, description="the 'where' — one line on where things stand (renders beside the phase chip); omit to keep")
    next: Optional[str] = Field(None, max_length=SHORT, description="'your move' — the one thing the user should do or decide now; omit to keep, empty string to clear")


class DashboardModel(_Base):
    title: str = Field("", max_length=SHORT)
    phase: Phase = Phase.planning
    turn: int = 0
    seq: int = 0
    tldr: Tldr = Field(default_factory=Tldr)
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


class TodoRemove(_OpBase):
    op: Literal["todo.remove"]
    id: str = Field(description="id of the plan step to drop — only when it is genuinely no longer needed")
    reason: str = Field("", max_length=SHORT, description="one-line motivation")


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


class HeadsupUpsert(_OpBase):
    op: Literal["headsup.upsert"]
    id: Optional[str] = Field(None, description="existing row id; omit to create a new one")
    sev: Optional[Sev] = Field(None, description="risk | flag | note; required when creating")
    what: Optional[str] = Field(None, max_length=SHORT, description="what you did/noticed; required when creating")
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


class FreeformRemove(_OpBase):
    op: Literal["freeform.remove"]
    id: str = Field(description="id of the freeform slot to remove")
    reason: str = Field("", max_length=SHORT, description="one-line motivation")


Op = Annotated[
    Union[
        TodoUpsert, TodoRemove,
        CtaUpsert, CtaRemove,
        HeadsupUpsert,
        JourneyAdd, JourneyUpdate, JourneyFold,
        FreeformUpsert, FreeformRemove,
    ],
    Field(discriminator="op"),
]

MAX_OPS = 40


class Update(_OpBase):
    """One turn's delta. Omitting an item keeps it; the server mints ids."""
    phase: Optional[Phase] = Field(None, description="set only when the phase changes")
    title: Optional[str] = Field(None, max_length=SHORT, description="set once at the start; rename rarely")
    tldr: Optional[TldrPatch] = Field(None, description="the glance lines; send only the fields that changed")
    ops: list[Op] = Field(default_factory=list, max_length=MAX_OPS,
                          description="the changes this turn; emit ONLY what materially changed, omit the rest")
