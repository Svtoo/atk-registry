"""Tests for the model + op-set schema (models.py).
Run with the pydantic venv: ../.venv/bin/python test_models.py
"""

import models
from testutil import run_module_tests


def test_update_validates_a_representative_op_set():
    payload = {
        "phase": "building",
        "ops": [
            {"op": "todo.upsert", "text": "write tests", "status": "open", "reason": "coverage"},
            {"op": "todo.upsert", "id": "t31", "status": "done", "reason": "done now"},
            {"op": "cta.upsert", "text": "confirm schema", "reason": "gate"},
            {"op": "headsup.upsert", "sev": "flag", "what": "chose upsert", "why": "less dup", "reason": "note"},
            {"op": "journey.add", "kind": "agent", "what": "chose side-channel", "why": "reliable"},
            {"op": "freeform.upsert", "id": "f2", "reason": "new", "htmlRef": "f2-body"},
            {"op": "cta.remove", "id": "c9", "reason": "resolved"},
        ],
    }
    update = models.Update.model_validate(payload)
    actual_types = [type(op).__name__ for op in update.ops]
    expected_types = ["TodoUpsert", "TodoUpsert", "CtaUpsert", "HeadsupUpsert",
                      "JourneyAdd", "FreeformUpsert", "CtaRemove"]
    assert actual_types == expected_types, actual_types


def test_todo_upsert_create_requires_text():
    create_without_text = {"ops": [{"op": "todo.upsert", "status": "open", "reason": "x"}]}
    raised = False
    try:
        models.Update.model_validate(create_without_text)
    except Exception:
        raised = True
    assert raised, "creating a todo (no id) without text must fail"

    update_by_id = {"ops": [{"op": "todo.upsert", "id": "t1", "status": "done", "reason": "x"}]}
    updated = models.Update.model_validate(update_by_id)
    assert updated.ops[0].id == "t1"


def test_headsup_upsert_create_requires_core_fields():
    missing_what_why = {"ops": [{"op": "headsup.upsert", "sev": "risk", "reason": "x"}]}
    raised = False
    try:
        models.Update.model_validate(missing_what_why)
    except Exception:
        raised = True
    assert raised, "creating a heads-up without sev/what/why must fail"


def test_update_rejects_unknown_op():
    bad = {"ops": [{"op": "todo.delete", "id": "t1"}]}
    raised = False
    try:
        models.Update.model_validate(bad)
    except Exception:
        raised = True
    assert raised, "an unknown op discriminator must fail validation"


def test_op_reason_is_optional_and_defaults_empty():
    # reason feeds the digest change-log; a missing reason must NOT fail the whole
    # regen (the agent drops it occasionally on real output), it just defaults empty.
    payload = {"ops": [{"op": "cta.remove", "id": "c1"}]}
    update = models.Update.model_validate(payload)
    assert update.ops[0].reason == ""


def test_update_rejects_too_many_ops():
    one_op = {"op": "cta.upsert", "text": "x", "reason": "r"}
    over_cap = {"ops": [one_op for _ in range(models.MAX_OPS + 1)]}
    raised = False
    try:
        models.Update.model_validate(over_cap)
    except Exception:
        raised = True
    assert raised, "op count over MAX_OPS must fail validation"


def test_empty_update_is_valid():
    empty = models.Update.model_validate({})
    assert empty.ops == []
    assert empty.phase is None


def test_unknown_keys_in_agent_payloads_fail_loudly():
    # The digest shows friendly labels; an agent copying them as field names
    # must get a validation error (feeding the corrective retry), not a
    # silently-empty patch.
    wrong_key = {"tldr": {"what": "copied from the digest label"}}
    raised = False
    try:
        models.Update.model_validate(wrong_key)
    except Exception:
        raised = True
    assert raised, "an unknown tldr key must fail validation, not no-op"


if __name__ == "__main__":
    run_module_tests(globals())
