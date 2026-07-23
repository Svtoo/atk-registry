"""Wire I/O for the agent's op-set.

The agent replies in XML-delimited blocks, located by literal string search
(not an XML parser): an `<update>` block holding the op-set as JSON, then one
`<freeform ref="…">` block per freeform body. Anything outside the blocks —
prose the model emits before, between, or after — is ignored. If the `<update>`
block is missing or unclosed the whole reply is treated as no data and the
dashboard is left unchanged (graceful failure). A freeform body that is missing
or over the size limit drops only its own op; the rest of the update still
applies.
"""
import json

from pydantic import ValidationError

from models import HTML_MAX, Update

_UPDATE_OPEN = "<update>"
_UPDATE_CLOSE = "</update>"
_FF_OPEN_PREFIX = '<freeform ref="'
_FF_CLOSE = "</freeform>"


class AgentOutputError(Exception):
    """The agent output had no usable `<update>` block. The caller keeps the
    prior model and live dashboard untouched (non-destructive) and may retry."""


def _slice_between(text: str, open_tag: str, close_tag: str, start: int = 0):
    """Literal-search the content between the first `open_tag` and the next
    `close_tag` after it. Returns (content, end_index) or (None, -1) if either
    tag is absent (a missing or unclosed block)."""
    i = text.find(open_tag, start)
    if i == -1:
        return None, -1
    body_start = i + len(open_tag)
    j = text.find(close_tag, body_start)
    if j == -1:
        return None, -1
    return text[body_start:j], j + len(close_tag)


def _extract_freeform_bodies(raw: str) -> "dict[str, str]":
    """Collect every well-formed `<freeform ref="ID">…</freeform>` block by
    literal search. An unclosed freeform block is skipped (no body for that
    ref), which downstream drops just that freeform op."""
    bodies: "dict[str, str]" = {}
    pos = 0
    while True:
        i = raw.find(_FF_OPEN_PREFIX, pos)
        if i == -1:
            break
        ref_start = i + len(_FF_OPEN_PREFIX)
        ref_end = raw.find('"', ref_start)
        gt = raw.find(">", ref_end) if ref_end != -1 else -1
        if ref_end == -1 or gt == -1:
            break  # malformed opening tag — stop scanning
        ref = raw[ref_start:ref_end]
        close = raw.find(_FF_CLOSE, gt)
        if close == -1:
            break  # unclosed final block — no body for this ref
        bodies[ref] = raw[gt + 1:close].strip("\n")
        pos = close + len(_FF_CLOSE)
    return bodies


def parse_output(raw: str) -> "tuple[Update, dict[str, str], list[str]]":
    """Split the agent output into a validated `Update`, a `{ref: raw_html}`
    map, and a list of human-readable notes about anything gracefully dropped.

    Raises `AgentOutputError` when there is no usable `<update>` block (missing,
    unclosed, not JSON, or schema-invalid) — the whole turn is then discarded
    non-destructively. A freeform body that is missing or oversized is dropped
    from the op-set (with a note), not raised, so one bad visual never sinks an
    otherwise-good update.
    """
    json_part, _ = _slice_between(raw, _UPDATE_OPEN, _UPDATE_CLOSE)
    if json_part is None:
        raise AgentOutputError(
            "no complete <update>…</update> block in the reply — discarded, "
            "dashboard left unchanged"
        )
    try:
        data = json.loads(json_part.strip())
    except json.JSONDecodeError as e:
        raise AgentOutputError(f"<update> block is not valid JSON: {e}") from e
    try:
        update = Update.model_validate(data)
    except ValidationError as e:
        raise AgentOutputError(f"op-set failed schema validation: {e}") from e

    bodies = _extract_freeform_bodies(raw)
    notes: list = []
    kept_ops = []
    for op in update.ops:
        if op.op != "freeform.upsert":
            kept_ops.append(op)
            continue
        body = bodies.get(op.html_ref)
        if body is None:
            notes.append(f"dropped freeform.upsert ref={op.html_ref!r}: no matching <freeform> block")
            continue
        if len(body) > HTML_MAX:
            notes.append(
                f"dropped freeform.upsert ref={op.html_ref!r}: body {len(body)} chars "
                f"over the {HTML_MAX} limit"
            )
            continue
        kept_ops.append(op)
    update.ops = kept_ops
    return update, bodies, notes
