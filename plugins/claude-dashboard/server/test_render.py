"""Tests for render.py — DashboardModel -> HTML body fragment.
Locks the exact class contract the layout + dashboard.js wire to (watch-deck ack
buttons, todo-list, timeline). Run: ../.venv/bin/python test_render.py
"""

import models
from models import (
    CtaItem, DashboardModel, FreeformSlot, HeadsupItem, JourneyItem, Tldr,
    TodoItem, JourneyKind, Phase, Sev, TodoStatus,
)
from render import block_sizes, render
from testutil import run_module_tests


def test_block_sizes_covers_every_card_and_matches_the_rendered_bytes():
    slot_html = '<section class="card free-form">FF</section>'
    m = DashboardModel(
        title="Sizes", phase=Phase.building, tldr=Tldr(essence="e"),
        todo=[TodoItem(id="t1", text="do it", status=TodoStatus.active)],
        headsup=[HeadsupItem(id="h1", sev=Sev.flag, what="w", why="y", where="z")],
        journey=[JourneyItem(id="j1", kind=JourneyKind.agent, what="w", why="y")],
        freeform=[FreeformSlot(id="f1", html=slot_html)],
    )
    sizes = block_sizes(m)
    assert set(sizes) == {"header", "cta", "todo", "headsup", "freeform", "journey"}
    assert sizes["freeform"] == len(slot_html.encode("utf-8")), "the freeform card's bytes match its body"
    # whole = sum of non-empty card bytes + one newline between each
    whole = render(m)
    nonempty = [v for v in sizes.values() if v]
    assert sum(nonempty) + (len(nonempty) - 1) == len(whole.encode("utf-8"))


def test_block_sizes_reports_zero_for_absent_cards():
    bare = DashboardModel(title="bare", phase=Phase.planning)
    sizes = block_sizes(bare)
    assert sizes["header"] > 0, "the header is always present"
    assert sizes["todo"] == 0 and sizes["journey"] == 0, "absent cards report 0, not missing keys"


def test_header_glance_grid_has_three_slots():
    title = "Glance grid"
    model = DashboardModel(title=title, phase=Phase.building,
                           tldr=Tldr(essence="server owns the state",
                                     status="phase-1 core done", next="review the header"))
    html = render(model)
    assert '<header class="session-header">' in html
    assert f"<h1>{title}</h1>" in html
    assert '<dl class="glance">' in html
    # the three fixed slots, in order
    assert html.index("<dt>what</dt>") < html.index("<dt>where</dt>") < html.index("<dt>your move</dt>")
    assert "server owns the state" in html          # what
    assert "phase-1 core done" in html              # where detail
    assert "review the header" in html              # your move


def test_header_falls_back_to_the_chats_own_title():
    chat_title = "Fix the login flow"
    untitled = DashboardModel()
    assert f"<h1>{chat_title}</h1>" in render(untitled, chat_title)
    assert "<h1>Session</h1>" in render(untitled), "no fallback still renders the generic header"
    model_title = "Model-chosen title"
    titled = DashboardModel(title=model_title)
    assert f"<h1>{model_title}</h1>" in render(titled, chat_title), \
        "a model-set title must win over the fallback"


def test_where_slot_carries_phase_chip():
    review = DashboardModel(title="X", phase=Phase.review, tldr=Tldr(status="PR #1905 in draft"))
    html = render(review)
    assert '<span class="phase-chip warn">Awaiting review</span>' in html
    assert "PR #1905 in draft" in html


def test_your_move_empty_reads_nothing_pending():
    html = render(DashboardModel(title="X", phase=Phase.planning))
    assert '<span class="phase-chip info">Planning</span>' in html
    assert '<div class="glance-row move clear">' in html
    assert "Nothing pending right now." in html


def test_cta_renders_items_and_all_clear_when_empty():
    with_cta = DashboardModel(cta=[CtaItem(id="c1", text="confirm the schema")])
    html = render(with_cta)
    assert '<section class="card questions">' in html
    assert '<ol class="questions-list">' in html
    assert '<span class="label">confirm the schema</span>' in html
    assert 'data-item-id="c1"' in html

    empty = render(DashboardModel())
    assert '<div class="all-clear">✓ Nothing pending</div>' in empty
    assert '<ol class="questions-list">' not in empty


def test_todo_renders_status_classes():
    model = DashboardModel(todo=[
        TodoItem(id="t1", text="did it", status=TodoStatus.done),
        TodoItem(id="t2", text="doing it", status=TodoStatus.active),
    ])
    html = render(model)
    assert '<ul class="todo-list">' in html
    # a lone done (run < DONE_FOLD_RUN) stays as its own row
    assert '<li class="done"><span class="label">did it</span></li>' in html
    assert '<li class="active checkable" data-item-id="t2">' in html
    assert '<span class="label">doing it</span>' in html


def test_todo_folds_long_done_runs_keeps_short_ones():
    model = DashboardModel(todo=[
        TodoItem(id="t1", text="alpha", status=TodoStatus.done),
        TodoItem(id="t2", text="beta", status=TodoStatus.done),
        TodoItem(id="t3", text="gamma", status=TodoStatus.done),
        TodoItem(id="t4", text="current work", status=TodoStatus.active),
        TodoItem(id="t5", text="lone done", status=TodoStatus.done),
    ])
    html = render(model)
    assert "3 done" in html, "a run of DONE_FOLD_RUN+ done must collapse into a count summary"
    assert "beta" not in html, "the middle of a folded run is dropped from the summary"
    assert '<li class="active checkable" data-item-id="t4">' in html
    assert '<span class="label">current work</span>' in html
    assert '<li class="done"><span class="label">lone done</span></li>' in html


def test_headsup_row_matches_ack_contract():
    model = DashboardModel(headsup=[
        HeadsupItem(id="h1", sev=Sev.risk, what="chose upsert", why="could dup", where="fold.py"),
    ])
    html = render(model)
    assert '<table class="watch-deck">' in html
    assert "<thead>" in html and "<tbody>" in html
    assert '<tr data-row-id="h1">' in html
    assert '<td class="sev-col"><span class="risk">risk</span></td>' in html
    assert "<td>chose upsert</td>" in html
    assert '<td class="ack-col"><button class="ack-btn" type="button">acknowledge</button></td>' in html


def test_headsup_renders_all_rows_newest_first_no_cap():
    # far more than any old cap: every row must survive (full retention)
    items = [HeadsupItem(id=f"h{i}", sev=Sev.note, what=f"row {i}", why="w")
             for i in range(1, 21)]
    html = render(DashboardModel(headsup=items))
    for i in range(1, 21):
        assert f'data-row-id="h{i}"' in html, f"h{i} must not be dropped (no server cap)"
    assert html.index('data-row-id="h20"') < html.index('data-row-id="h1"'), "newest first"


def test_headsup_all_clear_when_empty():
    assert '<div class="all-clear">✓ Nothing surfaced this session</div>' in render(DashboardModel())


def test_journey_marks_last_row_current_with_here_badge():
    model = DashboardModel(journey=[
        JourneyItem(id="j1", kind=JourneyKind.user, what="asked", why="w"),
        JourneyItem(id="j2", kind=JourneyKind.agent, what="built", why="w"),
    ])
    html = render(model)
    assert '<ol class="timeline">' in html
    assert '<span class="badge user">👤</span>' in html
    assert '<li class="current">' in html
    assert '<span class="badge here">📍</span>' in html
    assert html.count('<li class="current">') == 1, "only the most recent beat is current"


def test_freeform_body_is_emitted_verbatim_as_the_card():
    # the agent owns the whole card: the body IS the full <section> — no server wrap
    body = ('<section class="card free-form"><h2>arch</h2>'
            '<svg><text>a raw ]]> and <code>{"k":1}</code></text></svg></section>')
    model = DashboardModel(freeform=[FreeformSlot(id="f1", html=body, hash="x")])
    html = render(model)
    assert body in html, "the agent's full freeform card must be emitted verbatim (]]> intact)"
    assert html.count('class="card free-form"') == 1, "no double-wrapping: the body IS the card"
    assert "]]>" in html


def test_sections_render_in_canonical_order():
    model = DashboardModel(
        title="T",
        cta=[CtaItem(id="c1", text="q")],
        todo=[TodoItem(id="t1", text="x", status=TodoStatus.open)],
        headsup=[HeadsupItem(id="h1", sev=Sev.note, what="w", why="y")],
        journey=[JourneyItem(id="j1", kind=JourneyKind.agent, what="d", why="r")],
        freeform=[FreeformSlot(id="f1", html='<section class="card free-form"><p>v</p></section>', hash="h")],
    )
    html = render(model)
    # journey renders LAST (least useful day-to-day); freeform before it
    order = ["session-header", "card questions", "card todo",
             "card heads-up", "card free-form", "card journey"]
    positions = [html.index(tok) for tok in order]
    assert positions == sorted(positions), positions


def test_minimal_model_is_a_valid_fragment():
    html = render(DashboardModel(title="Hello", phase=Phase.planning))
    assert html.startswith('<header class="session-header">')
    assert html.rstrip().endswith("</section>")


# ── user verdicts + CTA age rot ────────────────────────────────────────

def test_cta_items_rot_one_step_per_turn_and_saturate_at_max():
    now_turn = 10
    brand_new_turn = 10
    one_turn_old = 9
    five_turns_old = 5
    nine_turns_old = 1
    m = DashboardModel(title="T", turn=now_turn, cta=[
        CtaItem(id="c0", text="brand new ask", created_turn=brand_new_turn),
        CtaItem(id="c1", text="one turn old", created_turn=one_turn_old),
        CtaItem(id="c2", text="five turns old", created_turn=five_turns_old),
        CtaItem(id="c3", text="nine turns old", created_turn=nine_turns_old),
    ])
    html = render(m)
    assert '<li class="age-0" data-item-id="c0"' in html, html
    assert '<li class="age-1" data-item-id="c1"' in html
    assert '<li class="age-5" data-item-id="c2"' in html
    # 9 turns old caps at the saturation class: bright red, no deeper stage.
    assert '<li class="age-6" data-item-id="c3"' in html
    assert "age-9" not in html
    assert 'title="waiting 1 turn"' in html
    assert 'title="waiting 9 turns"' in html, "tooltip keeps the true age past the cap"
    assert html.count('button class="verdict-btn trash" data-verdict="dismissed"') == 4, html


def test_todo_rows_get_clickable_checkbox_and_drop_button():
    open_text = "open task"
    done_text = "finished"
    blocked_text = "stuck"
    m = DashboardModel(title="T", turn=4, todo=[
        TodoItem(id="t1", text=open_text, status=TodoStatus.open),
        TodoItem(id="t2", text=done_text, status=TodoStatus.done),
        TodoItem(id="t3", text=blocked_text, status=TodoStatus.blocked),
    ])
    html = render(m)
    open_li = [ln for ln in html.splitlines() if open_text in ln][0]
    assert 'checkable' in open_li, open_li
    assert 'button class="todo-check"' in open_li and 'data-verdict="done"' in open_li
    assert 'verdict-btn trash' in open_li and 'data-verdict="dropped"' in open_li
    done_li = [ln for ln in html.splitlines() if done_text in ln][0]
    assert "todo-check" not in done_li and "trash" not in done_li, \
        "done rows are not interactive"
    blocked_li = [ln for ln in html.splitlines() if blocked_text in ln][0]
    assert "todo-check" not in blocked_li, "blocked keeps its ✗ marker"
    assert "verdict-btn trash" in blocked_li, "a blocked row can still be dropped"


if __name__ == "__main__":
    run_module_tests(globals())
