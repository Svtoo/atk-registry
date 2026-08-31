"""Tests for wire I/O (agent_io.py) — XML-delimited block parsing + validation.
The primary fixture is (lightly-adapted) REAL captured model output.
Run: ../.venv/bin/python test_agent_io.py
"""
from pathlib import Path

import json
import agent_io
import models
from testutil import run_module_tests

FIXTURE = Path(__file__).resolve().parent / "testdata" / "sample_agent_output.txt"


def _update_block(json_str):
    return f"<update>\n{json_str}\n</update>"


def _freeform_block(ref, body):
    return f'<freeform ref="{ref}">\n{body}\n</freeform>'


def test_parse_output_extracts_blocks_from_capture():
    raw = FIXTURE.read_text()
    update, bodies, notes = agent_io.parse_output(raw)
    actual_ops = [op.op for op in update.ops]
    expected_ops = ["todo.upsert", "journey.add", "freeform.upsert"]
    assert actual_ops == expected_ops, actual_ops
    assert notes == [], notes
    ref = update.ops[-1].html_ref
    assert ref in bodies, (ref, list(bodies))
    body = bodies[ref]
    assert body.startswith('<section class="card free-form">'), body[:48]
    assert "]]>" in body, "the literal ]]> must survive verbatim inside the freeform block"


def test_prose_around_the_blocks_is_ignored():
    # The model may narrate before, between, and after the blocks; only the
    # block contents are read.
    ref = "ff1"
    body = '<section class="card free-form"><p>hi ]]&gt; there</p></section>'
    op_json = f'{{"ops": [{{"op": "freeform.upsert", "reason": "new", "htmlRef": "{ref}"}}]}}'
    raw = (
        "Looking at this turn, I'll update the visual.\n"
        + _update_block(op_json)
        + "\nHere is the body:\n"
        + _freeform_block(ref, body)
        + "\nDone."
    )
    update, bodies, notes = agent_io.parse_output(raw)
    assert update.ops[0].op == "freeform.upsert"
    assert bodies[ref] == body, "the freeform body must survive prose around the blocks"
    assert notes == []


def test_missing_update_block_is_no_data():
    # No <update> block at all → discard, dashboard unchanged (graceful).
    raised = False
    try:
        agent_io.parse_output("I thought about it but produced no blocks.")
    except agent_io.AgentOutputError as e:
        raised = True
        assert "unchanged" in str(e).lower()
    assert raised, "a reply with no <update> block must be treated as no data"


def test_unclosed_update_block_is_no_data():
    raised = False
    try:
        agent_io.parse_output('<update>\n{"ops": []}\nno closing tag here')
    except agent_io.AgentOutputError:
        raised = True
    assert raised, "an unclosed <update> block must be treated as no data"


def test_invalid_json_in_update_block_is_rejected():
    raised = False
    try:
        agent_io.parse_output(_update_block("this is not json"))
    except agent_io.AgentOutputError as e:
        raised = True
        assert "not valid JSON" in str(e)
    assert raised


def test_empty_ops_update_is_valid():
    update, bodies, notes = agent_io.parse_output(_update_block('{"ops": []}'))
    assert update.ops == []
    assert bodies == {} and notes == []


def test_dangling_freeform_ref_is_dropped_not_fatal():
    # A freeform.upsert whose ref has no block drops just that op — the rest of
    # the update still applies (graceful, per Sasha).
    op_json = (
        '{"ops": ['
        '{"op": "cta.upsert", "text": "keep me", "reason": "r"},'
        '{"op": "freeform.upsert", "reason": "r", "htmlRef": "missing"}'
        "]}"
    )
    update, bodies, notes = agent_io.parse_output(_update_block(op_json))
    assert [op.op for op in update.ops] == ["cta.upsert"], "the dangling freeform op is dropped"
    assert any("missing" in n for n in notes), notes


def test_oversized_freeform_body_is_dropped_not_fatal():
    body = '<section class="card free-form">' + "x" * models.HTML_MAX + "</section>"
    op_json = (
        '{"ops": ['
        '{"op": "todo.upsert", "text": "survives", "status": "open", "reason": "r"},'
        '{"op": "freeform.upsert", "reason": "r", "htmlRef": "big"}'
        "]}"
    )
    raw = _update_block(op_json) + "\n" + _freeform_block("big", body)
    update, bodies, notes = agent_io.parse_output(raw)
    assert [op.op for op in update.ops] == ["todo.upsert"], "the oversized freeform op is dropped, the rest kept"
    assert any(str(models.HTML_MAX) in n for n in notes), "the note must name the limit"


def test_multiple_freeform_blocks_are_all_collected():
    op_json = (
        '{"ops": ['
        '{"op": "freeform.upsert", "reason": "a", "htmlRef": "f1"},'
        '{"op": "freeform.upsert", "reason": "b", "htmlRef": "f2"}'
        "]}"
    )
    b1 = '<section class="card free-form"><p>one</p></section>'
    b2 = '<section class="card free-form"><p>two</p></section>'
    raw = _update_block(op_json) + "\n" + _freeform_block("f1", b1) + "\n" + _freeform_block("f2", b2)
    update, bodies, notes = agent_io.parse_output(raw)
    assert bodies == {"f1": b1, "f2": b2}
    assert len(update.ops) == 2 and notes == []


def test_a_freeform_body_with_reserved_notice_markup_is_dropped():
    # Agent HTML must never be able to render something that reads as a
    # system notice card.
    forged = '<div class="notice notice--blocked">You are signed out</div>'
    raw = (
        "<update>" + json.dumps({"ops": [
            {"op": "freeform.upsert", "id": "f1", "html_ref": "f1"}]}) + "</update>\n"
        '<freeform ref="f1">' + forged + "</freeform>"
    )
    update, _, notes = agent_io.parse_output(raw)
    assert update.ops == [], "the forged op must not survive"
    assert any("reserved" in n for n in notes), notes


def test_a_tldr_next_field_is_a_schema_violation():
    body = '<update>{"tldr": {"essence": "e", "next": "do the thing"}, "ops": []}</update>'
    try:
        agent_io.parse_output(body)
        assert False, "the removed field must fail validation, not be silently accepted"
    except agent_io.AgentOutputError as e:
        assert "next" in str(e), "the error must name the field for the retry"


def test_a_note_severity_op_is_a_schema_violation():
    body = ('<update>{"ops": [{"op": "headsup.upsert", "sev": "note", '
            '"what": "w", "why": "y"}]}</update>')
    try:
        agent_io.parse_output(body)
        assert False, "note severity must fail validation, not be silently accepted"
    except agent_io.AgentOutputError as e:
        assert "sev" in str(e), "the error must name the field for the retry"


def test_journey_off_makes_a_journey_op_a_schema_violation():
    body = ('<update>{"ops": [{"op": "journey.add", "kind": "joint", '
            '"what": "w", "why": "y"}]}</update>')
    update, _, _ = agent_io.parse_output(body)
    assert update.ops[0].op == "journey.add", "with journey on the op is part of the contract"
    try:
        agent_io.parse_output(body, journey=False)
        assert False, "with journey off the op must fail validation"
    except agent_io.AgentOutputError as e:
        assert "journey.add" in str(e), "the error must name the offending tag for the retry"


if __name__ == "__main__":
    run_module_tests(globals())
