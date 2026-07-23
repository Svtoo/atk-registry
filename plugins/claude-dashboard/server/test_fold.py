"""Tests for fold.py — apply an agent Update onto the server's
DashboardModel. Pure function: same (model, update, bodies, turn) -> same new
model, input left untouched. `turn` is the absolute conversation turn.
Run: ../.venv/bin/python test_fold.py
"""

import models
from fold import apply_ops
from models import DashboardModel, Update
from testutil import run_module_tests


def _update(**kw):
    return Update.model_validate(kw)


def test_create_mints_ids_stamps_turn_and_advances_seq():
    model = DashboardModel()
    update = _update(ops=[
        {"op": "todo.upsert", "text": "write fold", "status": "open", "reason": "start"},
        {"op": "cta.upsert", "text": "confirm caps", "reason": "gate"},
    ])
    result = apply_ops(model, update, {}, turn=7)
    assert result.turn == 7, "model.turn is stamped with the passed conversation turn"
    assert len(result.todo) == 1 and len(result.cta) == 1
    new_todo = result.todo[0]
    assert new_todo.id, "a created todo must get a server-minted id"
    assert new_todo.changed_turn == 7, new_todo.changed_turn
    assert new_todo.text == "write fold"
    assert result.seq >= 2, "two creates must advance seq at least twice"
    assert new_todo.id != result.cta[0].id


def test_update_existing_by_id_preserves_untouched_fields():
    seeded = apply_ops(DashboardModel(), _update(ops=[
        {"op": "todo.upsert", "text": "the task", "status": "open", "reason": "create"},
    ]), {}, turn=1)
    todo_id = seeded.todo[0].id
    updated = apply_ops(seeded, _update(ops=[
        {"op": "todo.upsert", "id": todo_id, "status": "done", "reason": "finished"},
    ]), {}, turn=2)
    same = updated.todo[0]
    assert same.id == todo_id, "update must target the same item, not create a new one"
    assert len(updated.todo) == 1, "update must not append a duplicate"
    assert same.status == models.TodoStatus.done
    assert same.text == "the task", "text omitted on update must be preserved"
    assert same.changed_turn == 2, same.changed_turn


def test_unknown_id_update_is_skipped_not_created():
    update = _update(ops=[
        {"op": "todo.upsert", "id": "t999", "status": "done", "reason": "stale ref"},
    ])
    result = apply_ops(DashboardModel(), update, {}, turn=1)
    assert result.todo == [], "an update to a nonexistent id must be skipped, not invented"


def test_remove_deletes_the_item():
    seeded = apply_ops(DashboardModel(), _update(ops=[
        {"op": "cta.upsert", "text": "a blocker", "reason": "create"},
    ]), {}, turn=1)
    cta_id = seeded.cta[0].id
    result = apply_ops(seeded, _update(ops=[
        {"op": "cta.remove", "id": cta_id, "reason": "resolved"},
    ]), {}, turn=2)
    assert result.cta == [], "remove must delete the item"


def test_todo_remove_drops_the_step():
    # The plan may shrink: a step that is genuinely no longer needed (or a
    # work-log entry being consolidated into a real plan step) is removable.
    kept_text, dropped_text = "real plan step", "obsolete step"
    seeded = apply_ops(DashboardModel(), _update(ops=[
        {"op": "todo.upsert", "text": kept_text, "status": "open", "reason": "plan"},
        {"op": "todo.upsert", "text": dropped_text, "status": "open", "reason": "plan"},
    ]), {}, turn=1)
    result = apply_ops(seeded, _update(ops=[
        {"op": "todo.remove", "id": seeded.todo[1].id, "reason": "not needed"},
    ]), {}, turn=2)
    assert [t.text for t in result.todo] == [kept_text], "todo.remove must drop the step"


def test_journey_add_appends_without_server_side_folding():
    # journey.add is pure append now; compression is agent-driven (journey.fold),
    # so the server no longer auto-folds at a cap.
    n = models.JOURNEY_MAX + 3
    ops = [{"op": "journey.add", "kind": "agent", "what": f"beat {i}", "why": "why"}
           for i in range(n)]
    result = apply_ops(DashboardModel(), _update(ops=ops), {}, turn=1)
    assert len(result.journey) == n, "journey.add appends; the server does not auto-fold"
    assert result.journey[-1].what == f"beat {n - 1}"


def test_journey_update_rewrites_a_beat_keeping_its_turn():
    changelog_beat = "Turn 3: budget; defaults; footer fix"
    seeded = apply_ops(DashboardModel(), _update(ops=[
        {"op": "journey.add", "kind": "joint", "what": changelog_beat, "why": "w"},
    ]), {}, turn=3)
    beat = seeded.journey[0]

    rewritten = "Budget redefined as a threshold"
    result = apply_ops(seeded, _update(ops=[
        {"op": "journey.update", "id": beat.id, "what": rewritten},
    ]), {}, turn=9)
    assert result.journey[0].what == rewritten, "a bad beat must be rewritable"
    assert result.journey[0].why == "w", "an omitted field is preserved"
    assert result.journey[0].turn == 3, "the beat keeps the turn it happened on"


def test_journey_fold_replaces_oldest_with_the_agents_summary():
    seed_ops = [{"op": "journey.add", "kind": "agent", "what": f"beat {i}", "why": "w"}
                for i in range(models.JOURNEY_MAX + 2)]
    seeded = apply_ops(DashboardModel(), _update(ops=seed_ops), {}, turn=1)
    assert len(seeded.journey) == models.JOURNEY_MAX + 2

    folded = apply_ops(seeded, _update(ops=[
        {"op": "journey.fold", "what": "earlier: set up the thing", "why": "bounded"},
    ]), {}, turn=2)
    assert len(folded.journey) == models.JOURNEY_MAX, len(folded.journey)
    assert folded.journey[0].what == "earlier: set up the thing", "the summary is the agent's, placed first"
    assert folded.journey[-1].what == f"beat {models.JOURNEY_MAX + 1}", "the most recent beat is kept"


def test_freeform_stores_body_hashes_and_dedups():
    body_v1 = '<section class="card free-form"><p>hi ]]&gt; there</p></section>'
    seeded = apply_ops(DashboardModel(), _update(ops=[
        {"op": "freeform.upsert", "reason": "new", "htmlRef": "b"},
    ]), {"b": body_v1}, turn=1)
    slot = seeded.freeform[0]
    assert slot.html == body_v1, "the raw body must be stored verbatim"
    assert slot.hash, "a stored body must be hashed for dedup"
    assert slot.changed_turn == 1

    # re-upsert the SAME body -> not counted as a change (changed_turn stays)
    unchanged = apply_ops(seeded, _update(ops=[
        {"op": "freeform.upsert", "id": slot.id, "reason": "noop", "htmlRef": "b"},
    ]), {"b": body_v1}, turn=2)
    assert unchanged.freeform[0].changed_turn == 1, "an identical body must not bump changed_turn"

    # a DIFFERENT body -> bumps changed_turn + hash
    body_v2 = body_v1 + "<!-- edit -->"
    changed = apply_ops(unchanged, _update(ops=[
        {"op": "freeform.upsert", "id": slot.id, "reason": "edit", "htmlRef": "b"},
    ]), {"b": body_v2}, turn=3)
    assert changed.freeform[0].html == body_v2
    assert changed.freeform[0].changed_turn == 3, changed.freeform[0].changed_turn
    assert changed.freeform[0].hash != slot.hash


def test_journey_beats_are_stamped_with_the_conversation_turn():
    result = apply_ops(DashboardModel(), _update(ops=[
        {"op": "journey.add", "kind": "user", "what": "asked", "why": "w"},
    ]), {}, turn=42)
    assert result.journey[0].turn == 42, "a beat carries the absolute conversation turn, not a counter"


def test_phase_title_and_tldr_applied():
    result = apply_ops(DashboardModel(), _update(
        phase="building", title="Regen", tldr={"essence": "server owns state"},
    ), {}, turn=1)
    assert result.phase == models.Phase.building
    assert result.title == "Regen"
    assert result.tldr.essence == "server owns state"


def test_partial_tldr_update_preserves_the_other_lines():
    essence, status, first_move = "what-line", "where-line", "move-line"
    seeded = apply_ops(DashboardModel(), _update(
        tldr={"essence": essence, "status": status, "next": first_move},
    ), {}, turn=1)

    new_move = "new move"
    patched = apply_ops(seeded, _update(tldr={"next": new_move}), {}, turn=2)
    assert patched.tldr.essence == essence, "an omitted tldr field must be preserved"
    assert patched.tldr.status == status, "an omitted tldr field must be preserved"
    assert patched.tldr.next == new_move

    cleared = apply_ops(patched, _update(tldr={"next": ""}), {}, turn=3)
    assert cleared.tldr.next == "", "an explicit empty string clears the field"
    assert cleared.tldr.essence == essence


def test_update_without_reason_keeps_the_stored_reason():
    # All four upsert branches must preserve the stored reason when an update
    # op omits it (the reason feeds the digest's change motion).
    created_reason = "created for a good cause"
    body_a = '<section class="card free-form"><p>a</p></section>'
    body_b = '<section class="card free-form"><p>b</p></section>'
    seeded = apply_ops(DashboardModel(), _update(ops=[
        {"op": "todo.upsert", "text": "task", "status": "open", "reason": created_reason},
        {"op": "cta.upsert", "text": "ask", "reason": created_reason},
        {"op": "headsup.upsert", "sev": "note", "what": "w", "why": "y", "reason": created_reason},
        {"op": "freeform.upsert", "htmlRef": "ff", "reason": created_reason},
    ]), {"ff": body_a}, turn=1)

    updated = apply_ops(seeded, _update(ops=[
        {"op": "todo.upsert", "id": seeded.todo[0].id, "status": "done"},
        {"op": "cta.upsert", "id": seeded.cta[0].id, "text": "ask again"},
        {"op": "headsup.upsert", "id": seeded.headsup[0].id, "sev": "risk"},
        {"op": "freeform.upsert", "id": seeded.freeform[0].id, "htmlRef": "ff"},
    ]), {"ff": body_b}, turn=2)

    for item, branch in [(updated.todo[0], "todo"), (updated.cta[0], "cta"),
                         (updated.headsup[0], "headsup"), (updated.freeform[0], "freeform")]:
        assert item.reason == created_reason, \
            f"{branch}.upsert omitting reason must not blank the stored one (it feeds the digest)"


def test_apply_does_not_mutate_the_input_model():
    model = DashboardModel()
    apply_ops(model, _update(ops=[
        {"op": "todo.upsert", "text": "x", "reason": "r"},
    ]), {}, turn=5)
    assert model.turn == 0, "input turn must be untouched"
    assert model.todo == [], "input model must not be mutated (non-destructive)"


if __name__ == "__main__":
    run_module_tests(globals())
