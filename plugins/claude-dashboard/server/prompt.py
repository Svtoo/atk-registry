"""Regen prompt assembly: data in, strings out. The caller does all the I/O."""
import json
import re
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from digest import build_digest
from models import DashboardModel, Update

# The context policy is fixed, not user-configurable: the newest turn in full,
# a few prior turns as visible prose only.
FULL_TURNS = 1
LIGHT_TURNS = 2

# Physical ceiling on the transcript (estimate_words), sized to fit the model's
# ~200k-token context with headroom; an oversized turn is truncated, never skipped.
MAX_TRANSCRIPT_WORDS = 100_000

# A "word" is an alphanumeric run or a lone punctuation mark; unlike
# str.split(), this does not count a whitespace-poor JSON blob as one word.
_WORD_RE = re.compile(r"\w+|[^\w\s]")

# A run longer than this counts as multiple words, so character-dense runs
# (base64, hashes, minified code) are charged roughly like the tokens they cost.
_MAX_WORD_CHARS = 5


def _word_weight(run: str) -> int:
    """How many words one matched run is worth, charging a long run by length."""
    return (len(run) + _MAX_WORD_CHARS - 1) // _MAX_WORD_CHARS


def estimate_words(payload) -> int:
    """Token-approximating word count. Counts alphanumeric runs AND punctuation so
    token-dense tool output is not undercounted, and charges an over-long run by
    its length. Recurses through lists/dicts."""
    if isinstance(payload, str):
        return sum(_word_weight(m) for m in _WORD_RE.findall(payload))
    if isinstance(payload, (list, tuple)):
        return sum(estimate_words(x) for x in payload)
    if isinstance(payload, dict):
        return sum(estimate_words(v) for v in payload.values())
    return 0


def _cap_tool_body(body: str, max_words: int) -> str:
    """Head/tail-truncate one tool_result body to max_words, eliding the middle
    with a note; max_words <= 0 disables the cap."""
    if max_words <= 0:
        return body
    matches = list(_WORD_RE.finditer(body))
    weights = [_word_weight(m.group()) for m in matches]
    total = sum(weights)
    if total <= max_words:
        return body

    head_max = max(1, (max_words * 3) // 4)
    tail_max = max(1, max_words - head_max)

    head_n = kept_head = 0
    for i, w in enumerate(weights):
        if kept_head + w > head_max:
            break
        kept_head += w
        head_n = i + 1

    tail_start = len(matches)
    kept_tail = 0
    for i in range(len(matches) - 1, head_n - 1, -1):
        if kept_tail + weights[i] > tail_max:
            break
        kept_tail += weights[i]
        tail_start = i

    if head_n == 0 and tail_start == len(matches):
        # One run alone outweighs the whole budget: cut it by characters.
        return body[:max_words * _MAX_WORD_CHARS] + "\n[… truncated …]\n"

    elided = total - kept_head - kept_tail
    head_text = body[:matches[head_n - 1].end()] if head_n else ""
    tail_text = body[matches[tail_start].start():] if tail_start < len(matches) else ""
    return (
        head_text
        + f"\n[… {elided} words truncated — see the tool call in the chat for the full output …]\n"
        + tail_text
    )


def _count_tool_results(events: list) -> int:
    n = 0
    for ev in events:
        content = ev.get("message", {}).get("content")
        if isinstance(content, list):
            n += sum(1 for it in content if isinstance(it, dict) and it.get("type") == "tool_result")
    return n


def _image_placeholder(block: dict) -> str:
    """A note holding the fact that an image was there, without the base64
    payload the text-only regen subagent cannot read."""
    source = block.get("source") or {}
    data = source.get("data") or ""
    return f"[image omitted: {source.get('media_type', 'image')}, {len(data)} base64 chars]"


def _render_block(item: dict, tool_body_max: int = 0) -> str:
    """One content block of an event -> text, or "" if it carries nothing."""
    t = item.get("type")
    if t == "text":
        text = item.get("text", "")
        return text if text.strip() else ""
    if t == "thinking":
        thinking = (item.get("thinking", "") or item.get("text", "")).strip()
        return f"<thinking>\n{thinking}\n</thinking>" if thinking else ""
    if t == "image":
        return _image_placeholder(item)
    if t == "tool_use":
        inp = json.dumps(item.get("input", {}), indent=2, ensure_ascii=False)
        return f"<tool_use name={item.get('name', '?')!r} id={item.get('id', '?')!r}>\n{inp}\n</tool_use>"
    if t == "tool_result":
        inner = item.get("content")
        if isinstance(inner, str):
            body = inner
        elif isinstance(inner, list):
            parts = []
            for sub in inner:
                if not isinstance(sub, dict):
                    continue
                if sub.get("type") == "text":
                    parts.append(sub.get("text", ""))
                elif sub.get("type") == "tool_reference":
                    parts.append(f"[tool reference: {sub.get('name', '?')}]")
                elif sub.get("type") == "image":
                    parts.append(_image_placeholder(sub))
                else:
                    parts.append(json.dumps(sub, ensure_ascii=False))
            body = "\n".join(parts)
        else:
            body = ""
        return f"<tool_result for={item.get('tool_use_id', '?')!r}>\n{_cap_tool_body(body, tool_body_max)}\n</tool_result>"
    return ""


def render_events(events: list, full: bool = True, tool_body_max: int = 0) -> str:
    """Render JSONL events for the prompt. full=True keeps tool activity;
    full=False keeps only user messages and assistant prose."""
    out: list = []
    for ev in events:
        role = (ev.get("message", {}).get("role") or ev.get("type") or "?").upper()
        content = ev.get("message", {}).get("content")
        rendered: list = []
        if isinstance(content, str):
            if content.strip():
                rendered.append(content)
        elif isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                if not full and item.get("type") != "text":
                    continue
                block = _render_block(item, tool_body_max)
                if block:
                    rendered.append(block)
        if not rendered:
            continue
        out.append(f"[{role}]")
        out.extend(rendered)
        out.append("")
    return "\n".join(out).strip()


# ── the assembler ──────────────────────────────────────────────────────

class RegenPrompt(BaseModel):
    """All the data the assembler needs."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    dashboard: DashboardModel                       # current server-owned state
    turns: list = Field(default_factory=list)       # all turns, oldest->newest (raw JSONL events)
    turn_no: int = 0                                # absolute conversation turn
    system_template: str = ""                       # SYSTEM.md content


@dataclass
class AssembledPrompt:
    """What the model gets, plus the size stats the caller logs."""
    system: str
    user: str
    transcript_words: int
    truncated: bool          # a turn was head/tail truncated to fit


def _strip_schema_titles(node):
    """Drop pydantic's auto-generated "title" keys; they restate field names."""
    if isinstance(node, dict):
        return {k: _strip_schema_titles(v) for k, v in node.items() if k != "title"}
    if isinstance(node, list):
        return [_strip_schema_titles(x) for x in node]
    return node


def _output_format() -> str:
    schema = json.dumps(_strip_schema_titles(Update.model_json_schema()), indent=1)
    return (
        "<output_format>\n"
        "Reply with an <update> block holding the op-set as one JSON object, "
        "then one <freeform> block per freeform.upsert holding that slot's raw "
        "HTML body:\n\n"
        "<update>\n"
        "{ the op-set JSON }\n"
        "</update>\n"
        '<freeform ref="THE_HTMLREF">\n'
        '<section class="card free-form">…</section>\n'
        "</freeform>\n\n"
        "The op-set JSON matches this schema:\n"
        f"{schema}\n"
        "Only the content inside the blocks is read — text before, between, or "
        "after is ignored, so you may reason first if you need to. Always close "
        "the <update> block: if it is missing or unclosed the whole reply is "
        "discarded and the dashboard is left unchanged.\n"
        "</output_format>"
    )


def _task(turn_no: int) -> str:
    return (
        f"This is conversation turn {turn_no}. Emit the delta for everything "
        "that changed since the state above, plus repairs: listed items that "
        "violate their section's definition, or that newer facts contradict, "
        "get consolidated, rewritten, or removed. Repair incrementally — a "
        "handful of repair ops per turn, worst violation first; the dashboard "
        "converges over turns. Omit healthy unchanged items; an empty ops list "
        "is valid only when nothing changed and nothing is broken. Never create "
        "a duplicate of an item already listed — update it by id."
    )


def assemble_prompt(rp: RegenPrompt) -> AssembledPrompt:
    """Turn structured data into the exact (system, user) strings for `claude -p`."""
    window = rp.turns[-(FULL_TURNS + LIGHT_TURNS):]
    base = rp.turn_no - len(window)
    n = len(window)

    # [turn_no, is_full, events, rendered_text]; older turns prose-only, newest full.
    rendered = [
        [base + i + 1, i >= n - FULL_TURNS, t, render_events(t, full=(i >= n - FULL_TURNS))]
        for i, t in enumerate(window)
    ]

    # Physical fit: when a full turn overflows the budget, its tool bodies are
    # capped to a share of it; the turn itself is never skipped.
    truncated = False
    light_words = sum(estimate_words(r[3]) for r in rendered if not r[1])
    budget = MAX_TRANSCRIPT_WORDS - light_words
    full_rows = [r for r in rendered if r[1]]
    if full_rows and sum(estimate_words(r[3]) for r in full_rows) > budget:
        per_turn = max(1, budget // len(full_rows))
        for r in full_rows:
            if estimate_words(r[3]) > per_turn:
                truncated = True
                tool_body_max = max(1, per_turn // max(1, _count_tool_results(r[2])))
                r[3] = render_events(r[2], full=True, tool_body_max=tool_body_max)

    turn_blocks = [
        f'<turn n="{num}">\n{text}\n</turn>'
        for num, _is_full, _events, text in rendered if text.strip()
    ]
    transcript = "\n".join(turn_blocks)

    system = f"{rp.system_template.strip()}\n\n{_output_format()}"
    user = (
        f'<dashboard_state turn="{rp.turn_no}">\n{build_digest(rp.dashboard, now_turn=rp.turn_no)}\n</dashboard_state>\n\n'
        f'<transcript note="recent conversation; the newest turn in full with tool calls, earlier turns as prose">\n'
        f"{transcript}\n</transcript>\n\n"
        f"<task>\n{_task(rp.turn_no)}\n</task>\n"
    )
    return AssembledPrompt(
        system=system, user=user,
        transcript_words=estimate_words(transcript), truncated=truncated,
    )
