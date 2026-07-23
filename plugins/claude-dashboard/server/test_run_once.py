"""End-to-end tests for regen.run_once — the full pipeline (retrieve, assemble,
invoke, parse, fold, render, write, persist) run in-process against a real temp
projects tree. Only invoke_claude is faked; no network, no `claude -p`.
Run: ../.venv/bin/python test_run_once.py
"""
import json
import tempfile
from pathlib import Path

import regen
from chat_state import ChatState
from store import DashboardStore
from testutil import run_module_tests

SESSION_UUID = "deadbeef-0000-0000-0000-000000000000"
PROJECT_HASH = "-proj"

TODO_TEXT = "wire the fold"
FREEFORM_BODY = '<section class="card free-form"><p>the design</p></section>'
FREEFORM_REF = "ff1"


def _valid_agent_output():
    ops = {
        "phase": "building",
        "title": "Run-once E2E",
        "tldr": {"essence": "pipeline check"},
        "ops": [
            {"op": "todo.upsert", "text": TODO_TEXT, "status": "active", "reason": "start"},
            {"op": "freeform.upsert", "reason": "new visual", "htmlRef": FREEFORM_REF},
        ],
    }
    return (
        f"<update>\n{json.dumps(ops)}\n</update>\n"
        f'<freeform ref="{FREEFORM_REF}">\n{FREEFORM_BODY}\n</freeform>\n'
    )


def _project_tree(n_turns):
    """A minimal real tree: plugin dir with SYSTEM.md + one session JSONL
    holding `n_turns` completed user->assistant turns."""
    root = Path(tempfile.mkdtemp())
    (root / "SYSTEM.md").write_text("You maintain a dashboard.")
    proj = root / PROJECT_HASH
    proj.mkdir()
    _write_jsonl(proj, n_turns)
    return root


def _write_jsonl(proj: Path, n_turns: int) -> None:
    lines = []
    for i in range(n_turns):
        lines.append(json.dumps(
            {"type": "user", "message": {"role": "user", "content": f"request {i}"}}))
        lines.append(json.dumps(
            {"type": "assistant",
             "message": {"role": "assistant", "content": [{"type": "text", "text": f"reply {i}"}]}}))
    (proj / f"{SESSION_UUID}.jsonl").write_text("\n".join(lines))


def _fake_invoke(bodies):
    """An invoke_claude stub that replies with `bodies` in order (the last one
    repeats) and records every user_message it was given."""
    calls = []

    def fake(*, system_prompt, user_message, model, timeout=0.0, on_proc=None):
        calls.append(user_message)
        body = bodies[min(len(calls) - 1, len(bodies) - 1)]
        return regen.RunResult(body=body, elapsed_seconds=0.1, returncode=0,
                               stderr="", input_tokens=10, output_tokens=5)
    return fake, calls


def _run(root, metrics=None):
    return regen.run_once(
        plugin_dir=root, projects_root=root,
        project_hash=PROJECT_HASH, session_uuid=SESSION_UUID,
        chat_state=ChatState(projects_root=root), metrics=metrics,
    )


def _last_metric_row(metrics):
    import sqlite3
    conn = sqlite3.connect(metrics._db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute("SELECT * FROM regen_metrics ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        conn.close()


def test_happy_path_writes_dashboard_and_persists_the_folded_model():
    n_turns = 2
    root = _project_tree(n_turns)
    metrics = DashboardStore(root / "metrics.db")
    fake, calls = _fake_invoke([_valid_agent_output()])
    original = regen.invoke_claude
    regen.invoke_claude = fake
    try:
        out = _run(root, metrics=metrics)
    finally:
        regen.invoke_claude = original

    html = out.read_text()
    assert TODO_TEXT in html, "the folded todo must render"
    assert FREEFORM_BODY in html, "the freeform body must render verbatim"

    model = ChatState(projects_root=root).get_model(PROJECT_HASH, SESSION_UUID)
    assert model is not None, "the folded model must be persisted"
    assert model["todo"][0]["text"] == TODO_TEXT
    assert model["turn"] == n_turns, "the model carries the absolute conversation turn"

    prompt = calls[0]
    assert "<dashboard_state" in prompt and "<task>" in prompt, \
        "the agent must receive the assembled XML-scaffolded prompt"
    assert metrics.totals()["regens"] == 1, "a successful regen must be recorded"


def test_invalid_output_is_retried_with_the_validators_feedback():
    garbage = "this is not json at all"
    root = _project_tree(1)
    fake, calls = _fake_invoke([garbage, _valid_agent_output()])
    original = regen.invoke_claude
    regen.invoke_claude = fake
    try:
        out = _run(root)
    finally:
        regen.invoke_claude = original

    assert len(calls) == 2, "one corrective retry expected"
    assert "REJECTED" in calls[1], "the retry message must say the output was rejected"
    assert "<update>" in calls[1], "the retry must carry the parser's own error (no update block)"
    assert TODO_TEXT in out.read_text(), "the corrected output must land"


def test_rejection_after_retry_is_non_destructive():
    garbage = "still not json"
    root = _project_tree(1)
    fake, calls = _fake_invoke([garbage, garbage])
    original = regen.invoke_claude
    regen.invoke_claude = fake
    raised = False
    try:
        _run(root)
    except regen.OutputRejected:
        raised = True
    finally:
        regen.invoke_claude = original

    assert raised, "two rejected attempts must surface OutputRejected"
    assert len(calls) == 2, "exactly one corrective retry, then surface"
    dash = root / PROJECT_HASH / SESSION_UUID / "dashboard.html"
    assert not dash.exists(), "a rejected regen must not write a dashboard"
    model = ChatState(projects_root=root).get_model(PROJECT_HASH, SESSION_UUID)
    assert model is None, "a rejected regen must not persist a model"


def test_second_regen_folds_onto_the_persisted_model():
    root = _project_tree(1)
    fake, _ = _fake_invoke([_valid_agent_output()])
    original = regen.invoke_claude
    regen.invoke_claude = fake
    try:
        _run(root)
    finally:
        regen.invoke_claude = original

    # The chat grows by one turn; the next regen adds a second todo.
    second_todo = "review the render"
    _write_jsonl(root / PROJECT_HASH, 2)
    second_output = "<update>\n" + json.dumps({"ops": [
        {"op": "todo.upsert", "text": second_todo, "status": "open", "reason": "next"},
    ]}) + "\n</update>"
    fake2, _ = _fake_invoke([second_output])
    regen.invoke_claude = fake2
    try:
        out = _run(root)
    finally:
        regen.invoke_claude = original

    model = ChatState(projects_root=root).get_model(PROJECT_HASH, SESSION_UUID)
    texts = [t["text"] for t in model["todo"]]
    assert texts == [TODO_TEXT, second_todo], \
        "state must accumulate across regens — the server owns it, not the turn"
    assert model["turn"] == 2, "the second regen advances the absolute turn"
    html = out.read_text()
    assert TODO_TEXT in html and second_todo in html


def test_success_records_input_output_and_block_telemetry():
    root = _project_tree(2)
    metrics = DashboardStore(root / "metrics.db")
    fake, _ = _fake_invoke([_valid_agent_output()])
    original = regen.invoke_claude
    regen.invoke_claude = fake
    try:
        out = _run(root, metrics=metrics)
    finally:
        regen.invoke_claude = original

    html_bytes = len(out.read_text().encode("utf-8"))
    row = _last_metric_row(metrics)
    assert row["kind"] == "ok"
    assert row["prompt_words"] > 0, "the assembled prompt size is recorded on success"
    assert row["output_bytes"] == html_bytes, "output size = the rendered dashboard's bytes"
    blocks = json.loads(row["block_sizes"])
    assert blocks["todo"] > 0, "the todo card's size is recorded"
    assert blocks["freeform"] == len(FREEFORM_BODY.encode("utf-8")), \
        "the freeform card's measured size matches its body"


def test_failure_carries_prompt_words_on_the_exception():
    # Only the registry knows about supersede, so run_once puts the input size on the exception.
    root = _project_tree(1)
    fake, _ = _fake_invoke(["not json", "still not json"])
    original = regen.invoke_claude
    regen.invoke_claude = fake
    exc = None
    try:
        _run(root)
    except regen.OutputRejected as e:
        exc = e
    finally:
        regen.invoke_claude = original

    assert exc is not None, "two rejects surface OutputRejected"
    assert getattr(exc, "prompt_words", None) is not None and exc.prompt_words > 0, \
        "the input size rides out on the exception for the registry's failure telemetry"


if __name__ == "__main__":
    run_module_tests(globals())
