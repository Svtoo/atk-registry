# Dashboard sections — requirements

The single source of truth for **what each section is**. `SYSTEM.md` (the agent's
instructions), the op-schema field descriptions in `models.py`, and `render.py` all
derive from this. Change the intent here first, then propagate — so the three never
drift and the prompt stays consistent.

Status: approved (2026-07-05). §5 records how the open questions were
resolved.

---

## 1. What the dashboard is for

The dashboard is the **visual, at-a-glance state of one conversation**, for a human
who reads structured / visual information far faster than chat prose.

It is **supplementary to the chat**, and its target state is that the human can rely
on it **instead of** reading the chat: when the call-to-action is clear, the to-do
is maintained, and heads-up is high-signal, the chat output is redundant.

Everything on it is high-signal — meant to be read **in full**. Every item is gold.
Conciseness serves that; noise defeats it.

---

## 2. Sections at a glance

| Section | Answers | Horizon | Direction | Empty is a valid state |
|---|---|---|---|---|
| **Glance** (header) | "Is this the chat I want, and what's the state?" | now | — | no |
| **Links** (chip strip under the header) | "Where do I jump from here?" | stable | agent → user | yes |
| **Call to action** | "What must I, the user, do right now?" | tactical | user → agent | **yes** (and good) |
| **Last turn** (strip atop the CTA card) | "What just happened?" | tactical | agent → user | yes |
| **To-do** | "How far are we, and what's left to finish?" | strategic | plan | yes |
| **Heads-up** | "What must I be aware of that I'd otherwise miss?" | mixed | agent → user | yes |
| **Journey** | "How did we get here?" | strategic | history | yes |
| **Freeform** | "What durable visual/reference material matters?" | strategic + tactical | canvas | yes |

---

## 3. Per-section requirements

Each section is defined by the same five fields.

### Glance (header)
- **Purpose** — the 10-second "is this the chat I want, and where are we?" This is
  the header's job, *not* the whole dashboard's.
- **Holds** — the title; and a fixed grid of *what* / *where*. The ask on the
  user lives only in Call to action — the header never mirrors it.
- **Excludes** — detail; anything that belongs in a section below.
- **Lifecycle** — rewritten each turn to reflect the current state.
- **Empty** — never; there is always a title + state.

### Links (chip strip under the header)
- **Purpose** — the handful of destinations the user keeps returning to for this
  chat: the issue, the PR, the branch, a design doc. Chosen design (2026-08-31,
  option A of three mockups): pill chips in a light strip between the header and
  the Call to action card — no card chrome, one line tall until it wraps.
- **Holds** — chips with a short kind tag (issue, pr, branch, doc, …), a label,
  and a URL; a URL-less chip (e.g. a branch name) renders as plain text.
- **Excludes** — anything volatile or one-off; a link dump. Navigation, not a
  bibliography.
- **Lifecycle** — agent-maintained: upserted when a destination appears or
  changes, removed when it stops mattering (a closed PR, a deleted branch).
- **Empty** — yes (renders nothing).

### Call to action (CTA)
- **Purpose** — the **most important** section, where the user's eye lands to learn
  what to do next **without reading the chat**. It distills any **input expected
  from the user** right now.
- **Holds** — concrete pending asks, decisions, and blockers that need the user.
- **Excludes** — strategic plan steps (those are **To-do**); filler. "Define the
  next step" is a useless action — if the only thing to surface is trivial or
  obvious, **leave CTA empty**.
- **Lifecycle** — an item is removed the instant it's resolved; this is a live
  blocker list, not a log.
- **Empty** — yes, and it's a *good* state: it means nothing is blocked on the user.

### Last turn (strip atop the CTA card)
- **Purpose** — what just happened, so the user reads neither the chat nor the
  transcript to know what the latest turn did. Chosen design (2026-08-31,
  option A of three mockups): rendered inside the Call to action card, above
  the asks, so summary + ask form one glance zone.
- **Holds** — 1–3 short outcome bullets for the newest turn only, plus the turn
  they describe (server-stamped). An op replaces the set wholesale — never an
  accumulating log.
- **Excludes** — process narration, anything older than the newest movement,
  and the cumulative "where are we" (that is `tldr.status`).
- **Lifecycle** — replaced whenever the work moves; when a turn changes nothing
  worth reading, the previous set stays, labeled with its own turn.
- **Empty** — yes (a fresh chat).

### To-do
- **Purpose** — the **strategic plan** for the work this conversation is doing, and
  the **progress toward finishing it**. It's the progress bar — "we're ~X% there" —
  that tells the user what's left even when the chat is long or has derailed.
- **Holds** — the finite set of strategic steps to complete the work. Ideally
  **defined once** when the work is scoped, then **checked off**.
- **Excludes** — tactical / per-turn items (those are **CTA**); churn.
- **Lifecycle** — define the plan, then check boxes. Items may be **dropped** when
  genuinely unnecessary — but never churned for the sake of change. **Stability and
  visible progression are the point**, not a constantly-rewritten list.
- **Ideal** — finite, with a clear "done".

### Heads-up
- **Purpose** — the agent's attention on the user's behalf: the record of what
  the user **likely missed** and might want to veto, undo, or double-check.
- **Holds** — `risk` and `flag` rows; the admission and exclusion rules live in
  `SYSTEM.md`. New rows never carry `note`; historic note rows remain rendered
  until acknowledged.
- **Excludes** — anything the user demonstrably already knows (the prompt
  carries the full gate).
- **Lifecycle** — the user acknowledges a row (it folds away, never deleted by the
  server). The agent may promote a row to CTA if it actually needs action. Each row
  carries a copy button that puts it on the clipboard as one plain line — provenance
  prefix plus the fields verbatim, no action words — for pasting into the chat.
- **Empty** — yes.

### Journey
- **Purpose** — the narrative of **how the conversation reached its current state**:
  the load-bearing decisions and inflection points, so the user can reconstruct the
  path.
- **Holds** — one beat per load-bearing moment. Routine exploration / tool turns are
  **not** beats.
- **Excludes** — minutiae, and anything that isn't a real decision or turning point.
- **Lifecycle** — bounded; old beats **compress with agent involvement**: when
  the digest flags the journey over its cap, the agent emits one `journey.fold`
  whose summary preserves the story of the oldest beats; the server keeps the
  most recent ones.
- **Empty** — yes (early in a chat).
- **Switchable** — the `CCD_JOURNEY` setting (default off) controls the whole
  section: while off, its prompt section (`SYSTEM_JOURNEY.md`), its ops, its
  digest block, and its card are all absent, and no beats are recorded — the
  off period is never backfilled.

### Freeform
- **Purpose** — the durable **visual + reference canvas**. Essential, not
  decorative — it carries meaning across the whole conversation.
- **Holds** — **both**:
  - *tactical* material relevant right now, and
  - *strategic* durable material: designs, long-term decisions, key terminology,
    diagrams, links — anything visual or referential that stays valuable across the
    conversation, **including context/terms the agent needs to retain** but that
    aren't otherwise surfaced.
- **Excludes** — superseded content; brainstorm rows once a direction is picked.
- **Lifecycle** — the agent owns the card body and drops superseded content
  within it; removing a whole card is the user's dismiss, never an agent op.
- **Empty** — yes.

---

## 4. How we write the agent's prompt (authoring principles)

These fix the "formatting all over the place" problem.

1. **No meta-narrative.** The agent does not need its version, history, or a story
   about itself. State the job and the rules. Less is more.
2. **Delimit our scaffolding with XML, not Markdown.** The state, transcript, and
   task are *our* structure; the content inside them is Markdown/HTML that the agent
   itself speaks — so Markdown headers for our structure blur into that content. Use
   tags like `<dashboard_state>`, `<transcript>`, `<task>` so the boundaries are
   unambiguous (and it's obvious where the transcript ends and the task begins).
3. **One place for section definitions** — this doc, at the right altitude
   (principle + mechanics), not CSS classes scattered through prose. The prompt
   references intent, not implementation.
4. **Drop empty blocks.** An empty `<thinking></thinking>` or empty content in the
   transcript is pure token waste — omit it.
5. **Consistent structure and formatting** across the whole prompt.

---

## 5. Open questions — resolved (2026-07-05)

1. **Journey compression** → server-flags, agent-summarizes: the digest flags
   "over cap", the agent emits one `journey.fold` with its own summary; the
   server keeps the most recent beats.
2. **Op JSON schema size** → auto-generated (no drift), then trimmed of pydantic
   auto-titles and rendered at indent=1 (~13.5k → ~9.5k chars). Field
   descriptions ARE the contract and always survive.
3. **Output framing** → the output format states the two parts as peers: one
   JSON op-set, then one fenced `html` block per `freeform.upsert`.
4. **Transcript form** → confirmed intentional: the agent sees the raw
   agent-perspective transcript (full `tool_use`/`tool_result`) — that is where
   silent changes and the highest-signal material live.
5. **Budget** → measured on RENDERED turns; threshold semantics (whole turns
   newest-first until the total reaches the soft budget, the crossing turn kept
   whole, the newest turn always included; a turn is never cut). Defaults: 4
   turns / 40,000 words; `-1` disables the soft budget; an unconditional
   200,000-word hard ceiling drops whole turns, even the newest. Oversized
   single tool bodies get a word-positional head/tail cap. Possible future:
   pure turn-count limiting (atk-registry issue #6).

**Freeform direction (2026-07-05):** freeform is the creative canvas —
never limit the agent's creativity. Long-term, `reason` substitutes for the
body in the agent's context (the digest already elides bodies) and the agent
gets read-back access to fetch a body before editing it (atk-registry issue
#8). Until then a 50,000-char fuse protects the regen timeout, with parse-time
feedback telling the agent to shrink.
