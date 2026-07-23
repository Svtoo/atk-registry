"""Tests for prompt assembly (prompt.py) — the context policy (newest turn full,
prior turns prose-only, monster turn truncated to fit) and the data-in/strings-out
assembler. Run: ../.venv/bin/python test_prompt.py
"""

from models import DashboardModel, Tldr
from prompt import (
    FULL_TURNS,
    LIGHT_TURNS,
    MAX_TRANSCRIPT_WORDS,
    RegenPrompt,
    _cap_tool_body,
    assemble_prompt,
    estimate_words,
    render_events,
)
from testutil import run_module_tests


def _text_turn(role, text):
    return [{"message": {"role": role, "content": [{"type": "text", "text": text}]}}]


def _tool_turn(user_text, tool_body):
    # a user request followed by an assistant tool call + its result
    return [
        {"type": "user", "message": {"role": "user", "content": user_text}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "on it"},
            {"type": "tool_use", "name": "Bash", "id": "tu1", "input": {"cmd": "ls"}},
        ]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tu1", "content": tool_body},
        ]}},
    ]


# ── word counting ──────────────────────────────────────────────────────

def test_estimate_words_counts_token_dense_content_not_just_whitespace():
    prose = "the quick brown fox jumps over the lazy dog"          # 9 whitespace words
    json_blob = '{"user":{"id":42,"tags":["a","b","c"]}}'          # ~1 whitespace word, token-dense
    prose_est = estimate_words(prose)
    blob_est = estimate_words(json_blob)
    assert prose_est >= 9, prose_est
    assert blob_est > prose_est, \
        f"token-dense blob undercounted ({blob_est}) vs short prose ({prose_est})"


def test_estimate_words_charges_a_character_dense_run_by_length():
    # A base64 run is one long alphanumeric match. Counted as a single word it is
    # ~5x cheaper than the tokens it really costs, which is how an image-heavy
    # turn slipped under MAX_TRANSCRIPT_WORDS and overflowed the model context.
    base64_run = "A" * 1000
    prose_of_same_length = " ".join(["word"] * 250)          # also 1000 chars
    blob_est = estimate_words(base64_run)
    prose_est = estimate_words(prose_of_same_length)
    assert blob_est >= 1000 // 5, \
        f"a {len(base64_run)}-char run must cost about len/5 words, got {blob_est}"
    assert blob_est >= prose_est * 0.5, \
        f"dense run ({blob_est}) must not be far cheaper than prose of equal length ({prose_est})"


def test_cap_tool_body_trims_a_body_made_of_dense_runs():
    # The cap must use the same weighting as estimate_words, or it under-trims
    # and the budget is not actually enforced.
    body = " ".join(["Q" * 200 for _ in range(200)])          # 200 dense runs
    capped = _cap_tool_body(body, max_words=100)
    assert estimate_words(capped) <= 200, \
        f"capped body still weighs {estimate_words(capped)} words"
    assert len(capped) < len(body), "an oversized dense body must shrink"


# ── images never reach the prompt ──────────────────────────────────────

def test_image_inside_a_tool_result_is_replaced_by_a_placeholder():
    payload = "B" * 5000
    events = _tool_turn("screenshot it", [
        {"type": "text", "text": "here is the screen"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": payload}},
    ])
    rendered = render_events(events, full=True)
    assert payload not in rendered, "base64 image data must never reach the prompt"
    assert "image omitted" in rendered, "the image should leave a note behind"
    assert "here is the screen" in rendered, "surrounding text must survive"


def test_a_screenshot_heavy_turn_stays_small():
    # The real failure: five screenshots were 84% of a 970k-char prompt.
    shot = {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                        "data": "C" * 160_000}}
    events = _tool_turn("look", [shot for _ in range(5)])
    rendered = render_events(events, full=True)
    assert estimate_words(rendered) < 1000, \
        f"five screenshots must not dominate the prompt, got {estimate_words(rendered)} words"


# ── rendering: full vs prose-only ──────────────────────────────────────

def test_render_events_full_keeps_tool_output():
    huge = "z " * 5000
    events = [{"message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": huge},
    ]}}]
    rendered = render_events(events, full=True)
    assert rendered.count("z") >= 5000, "full render keeps tool output"


def test_render_events_light_drops_tool_activity_keeps_prose():
    prose = "the user asked for X"
    events = [
        {"message": {"role": "user", "content": prose}},
        {"message": {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "hmm"},
            {"type": "text", "text": "here is the plan"},
            {"type": "tool_use", "name": "Bash", "id": "t1", "input": {"cmd": "rm"}},
        ]}},
        {"message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "SECRET_TOOL_OUTPUT"},
        ]}},
    ]
    light = render_events(events, full=False)
    assert prose in light and "here is the plan" in light, "prose survives the light render"
    assert "SECRET_TOOL_OUTPUT" not in light, "tool_result bodies are dropped in the light render"
    assert "tool_use" not in light and "<thinking>" not in light, "tool calls + thinking dropped"


def test_render_events_drops_empty_thinking_and_empty_events():
    empty_thinking_turn = [{"message": {"role": "assistant", "content": [
        {"type": "thinking", "thinking": "   "},
        {"type": "text", "text": ""},
    ]}}]
    rendered = render_events(empty_thinking_turn)
    assert rendered == "", "an event with only empty blocks must render nothing"


# ── per-tool truncation (physical fit, mirrors the harness) ────────────

def test_cap_tool_body_head_tail_truncates_an_oversized_body():
    words = [f"w{i}" for i in range(1000)]
    body = " ".join(words)
    capped = _cap_tool_body(body, max_words=100)
    assert estimate_words(capped) < 1000, "an oversized tool body must shrink"
    assert "w0" in capped, "the head survives"
    assert "w999" in capped, "the tail survives"
    assert "w500" not in capped, "the bulky middle is elided"
    assert "truncated" in capped, "the cut is marked like the harness's own"


def test_cap_tool_body_leaves_a_fitting_body_untouched():
    body = "small tool output"
    assert _cap_tool_body(body, max_words=10_000) == body


def test_render_full_emits_tool_results_verbatim_by_default():
    # The transcript already carries the harness's truncations; with no cap we
    # replay tool output exactly as the agent saw it.
    events = _tool_turn("do it", "EXACT_TOOL_OUTPUT " * 100)
    rendered = render_events(events, full=True)
    assert "EXACT_TOOL_OUTPUT" in rendered
    assert "truncated" not in rendered, "no cap → verbatim, no invented truncation"


# ── the context window ─────────────────────────────────────────────────

def test_assemble_windows_to_recent_turns_newest_full_prior_prose():
    # Build more turns than the window; only the last FULL+LIGHT are used,
    # the newest FULL_TURNS with tool activity, the rest as prose only.
    n = FULL_TURNS + LIGHT_TURNS + 3
    turns = [_tool_turn(f"request {i}", f"TOOLOUT{i}") for i in range(n)]
    rp = RegenPrompt(dashboard=DashboardModel(), turns=turns, turn_no=n,
                     system_template="R")
    out = assemble_prompt(rp)

    # oldest turns fall outside the window entirely
    assert "request 0" not in out.user, "turns older than the window are dropped"
    # the newest turn keeps its tool output; a prior (still-in-window) turn does not
    assert f"TOOLOUT{n - 1}" in out.user, "the newest turn is full (tool output kept)"
    assert f"TOOLOUT{n - 2}" not in out.user, "a prior turn is prose-only (tool output dropped)"
    assert f"request {n - 2}" in out.user, "but the prior turn's prose is kept for context"
    assert f'<turn n="{n}">' in out.user, "the newest turn carries its absolute number"


def test_monster_newest_turn_has_its_tool_body_capped_not_skipped():
    monster_body = "blob " * (MAX_TRANSCRIPT_WORDS + 5000)
    turns = [_tool_turn("do the big thing", monster_body)]
    rp = RegenPrompt(dashboard=DashboardModel(), turns=turns, turn_no=1,
                     system_template="R")
    out = assemble_prompt(rp)
    assert out.truncated, "a turn over the context ceiling must be capped"
    assert estimate_words(out.user) < MAX_TRANSCRIPT_WORDS + 20_000, "the prompt must fit the ceiling"
    assert '<turn n="1">' in out.user, "the turn is still present — capped, never skipped"
    assert "do the big thing" in out.user, "the request + turn structure survive (per-tool cap, not a blind turn cut)"
    assert "truncated" in out.user, "the oversized tool body carries the harness-style note"


# ── the assembler ──────────────────────────────────────────────────────

def test_assemble_prompt_is_xml_structured_data_in_strings_out():
    dashboard = DashboardModel(title="T", turn=6, tldr=Tldr(essence="e", status="s", next="n"))
    turns = [_text_turn("assistant", "older beat"), _text_turn("assistant", "latest beat")]
    rp = RegenPrompt(dashboard=dashboard, turns=turns, turn_no=6, system_template="ROLE AND RULES")
    out = assemble_prompt(rp)

    assert "ROLE AND RULES" in out.system
    assert "<output_format>" in out.system
    assert "freeform.upsert" in out.system, "the schema must flow into the system prompt"
    assert '"title"' not in out.system, "pydantic auto-titles are stripped from the schema"
    assert "one-line motivation" in out.system, "field descriptions are the contract — they survive"

    assert '<dashboard_state turn="6">' in out.user
    assert "<transcript" in out.user
    assert '<turn n="6">' in out.user and "latest beat" in out.user
    assert "<task>" in out.user and "conversation turn 6" in out.user
    assert out.truncated is False


if __name__ == "__main__":
    run_module_tests(globals())
