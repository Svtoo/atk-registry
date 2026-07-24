"""Tests for the dashboard-model persistence in ChatState.
Run: python3 test_chat_state.py  (no pydantic needed — plain JSON dicts)
"""
import json
import tempfile
from pathlib import Path

from chat_state import ChatState
from testutil import run_module_tests


def _fresh_state(tmp):
    h, s = "proj", "sess"
    (tmp / h / s).mkdir(parents=True)
    (tmp / h / s / "state.json").write_text(json.dumps({"version": 1, "acks": {}, "regenErrors": []}))
    return ChatState(projects_root=tmp), h, s


def test_set_and_get_model_round_trips():
    tmp = Path(tempfile.mkdtemp())
    cs, h, s = _fresh_state(tmp)
    model = {"title": "T", "turn": 3, "phase": "building", "seq": 5}
    cs.set_model(h, s, model)
    actual = cs.get_model(h, s)
    assert actual == model, actual


def test_model_survives_an_ack_write():
    # the clobber guard: _read_locked must preserve "model" so an acks write
    # (which reconstructs the dict) never drops the persisted model.
    tmp = Path(tempfile.mkdtemp())
    cs, h, s = _fresh_state(tmp)
    model = {"title": "T", "turn": 7}
    cs.set_model(h, s, model)
    cs.set_ack(h, s, "row-1")
    assert cs.get_model(h, s) == model, "an ack write dropped the model"
    assert cs.snapshot(h, s)["acks"].get("row-1"), "the ack itself was lost"


def test_get_model_is_none_for_fresh_chat():
    tmp = Path(tempfile.mkdtemp())
    cs, h, s = _fresh_state(tmp)
    assert cs.get_model(h, s) is None, "a chat with no persisted model yet returns None"


def test_set_model_prunes_acks_with_no_matching_row():
    # Acks are keyed by heads-up row id. Heads-up rows are permanent (never
    # removed by the agent), but an ack with no matching row in the model — a
    # stale or bogus entry — must not pile up in state.json forever.
    tmp = Path(tempfile.mkdtemp())
    cs, h, s = _fresh_state(tmp)
    real_row, orphan_row = "h1", "h2"
    cs.set_ack(h, s, real_row)
    cs.set_ack(h, s, orphan_row)
    cs.set_model(h, s, {"turn": 5, "headsup": [{"id": real_row, "sev": "note"}]})
    acks = cs.snapshot(h, s)["acks"]
    assert real_row in acks, "an ack whose row exists must survive"
    assert orphan_row not in acks, "an ack with no matching row must be pruned"


def test_resolve_errors_stamps_open_entries_only():
    tmp = Path(tempfile.mkdtemp())
    cs, h, s = _fresh_state(tmp)
    open_err = cs.record_error(h, s, kind="RegenTimeout", message="stopped")
    acked_err = cs.record_error(h, s, kind="SubprocessFailed", message="boom")
    cs.ack_error(h, s, acked_err["id"])
    cs.resolve_errors(h, s)
    by_id = {e["id"]: e for e in cs.snapshot(h, s)["regenErrors"]}
    assert by_id[open_err["id"]]["resolvedAt"] is not None, \
        "an open error must be stamped resolved on a later success"
    assert by_id[acked_err["id"]]["resolvedAt"] is None, \
        "an acknowledged error is already handled and must not be re-stamped"


def test_resolve_errors_is_idempotent():
    tmp = Path(tempfile.mkdtemp())
    cs, h, s = _fresh_state(tmp)
    err = cs.record_error(h, s, kind="RegenTimeout", message="stopped")
    cs.resolve_errors(h, s)
    first_stamp = {e["id"]: e for e in cs.snapshot(h, s)["regenErrors"]}[err["id"]]["resolvedAt"]
    cs.resolve_errors(h, s)
    second_stamp = {e["id"]: e for e in cs.snapshot(h, s)["regenErrors"]}[err["id"]]["resolvedAt"]
    assert second_stamp == first_stamp, "a second success must not move the resolved stamp"


def test_resolve_errors_survives_a_missing_session_dir():
    tmp = Path(tempfile.mkdtemp())
    cs = ChatState(projects_root=tmp)
    cs.resolve_errors("no-such", "session")


# ── user verdicts (done / dropped / dismissed) ─────────────────────────

def test_verdict_set_captures_item_text_and_clear_removes_it():
    cs, ph, su = _fresh_state(Path(tempfile.mkdtemp()))
    item_id = "c3"
    item_text = "answer me"
    verdict = "dismissed"
    cs.set_model(ph, su, {"cta": [{"id": item_id, "text": item_text}]})
    entry = cs.set_verdict(ph, su, "cta", item_id, verdict)
    assert entry["verdict"] == verdict and entry["text"] == item_text
    snap = cs.snapshot(ph, su)
    assert snap["verdicts"][f"cta:{item_id}"]["verdict"] == verdict, snap["verdicts"]
    cs.clear_verdict(ph, su, "cta", item_id)
    assert cs.snapshot(ph, su)["verdicts"] == {}


def test_verdict_for_unknown_item_records_empty_text():
    cs, ph, su = _fresh_state(Path(tempfile.mkdtemp()))
    entry = cs.set_verdict(ph, su, "todo", "t404", "dropped")
    assert entry["text"] == ""


def test_set_model_prunes_absorbed_done_verdicts_and_caps_the_rest():
    cs, ph, su = _fresh_state(Path(tempfile.mkdtemp()))
    done_id = "t1"
    dropped_id = "t2"
    cs.set_model(ph, su, {"todo": [
        {"id": done_id, "text": "a", "status": "open"},
        {"id": dropped_id, "text": "b", "status": "open"},
    ]})
    cs.set_verdict(ph, su, "todo", done_id, "done")
    cs.set_verdict(ph, su, "todo", dropped_id, "dropped")
    # The fold marks the done item done and removes the dropped one.
    cs.set_model(ph, su, {"todo": [{"id": done_id, "text": "a", "status": "done"}]})
    verdicts = cs.snapshot(ph, su)["verdicts"]
    assert f"todo:{done_id}" not in verdicts, "absorbed done verdict must be pruned"
    assert f"todo:{dropped_id}" in verdicts, "dropped stays as never-re-add memory"

    from chat_state import MAX_VERDICTS_PER_CHAT
    for i in range(MAX_VERDICTS_PER_CHAT + 10):
        cs.set_verdict(ph, su, "todo", f"x{i}", "dropped")
    cs.set_model(ph, su, {"todo": []})
    assert len(cs.snapshot(ph, su)["verdicts"]) == MAX_VERDICTS_PER_CHAT


def test_verdict_validation_rejects_garbage():
    cs, ph, su = _fresh_state(Path(tempfile.mkdtemp()))
    assert cs.is_valid_verdict("todo", "done")
    assert cs.is_valid_verdict("todo", "dropped")
    assert cs.is_valid_verdict("cta", "dismissed")
    assert not cs.is_valid_verdict("cta", "done"), "cta has exactly one verb"
    assert not cs.is_valid_verdict("todo", "dismissed")
    assert not cs.is_valid_verdict("freeform", "done"), "only todo and cta take verdicts"


def test_legacy_state_files_normalize_verdicts_to_empty():
    cs, ph, su = _fresh_state(Path(tempfile.mkdtemp()))
    path = cs.state_path(ph, su)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"version": 1, "acks": {}, "regenErrors": []}')
    snap = cs.snapshot(ph, su)
    assert snap["verdicts"] == {}, snap


if __name__ == "__main__":
    run_module_tests(globals())
