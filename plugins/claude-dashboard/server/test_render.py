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
    assert set(sizes) == {"header", "links", "cta", "todo", "headsup", "freeform", "journey"}
    assert sizes["freeform"] > len(slot_html.encode("utf-8")), \
        "the freeform block is the body plus the slot wrapper chrome"
    # whole = sum of non-empty card bytes + one newline between each
    whole = render(m)
    nonempty = [v for v in sizes.values() if v]
    assert sum(nonempty) + (len(nonempty) - 1) == len(whole.encode("utf-8"))


def test_block_sizes_reports_zero_for_absent_cards():
    bare = DashboardModel(title="bare", phase=Phase.planning)
    sizes = block_sizes(bare)
    assert sizes["header"] > 0, "the header is always present"
    assert sizes["todo"] == 0 and sizes["journey"] == 0, "absent cards report 0, not missing keys"


def test_header_puts_state_in_a_strip_above_the_title():
    title = "Glance grid"
    model = DashboardModel(title=title, phase=Phase.building, turn=12, turn_base=34,
                           tldr=Tldr(essence="server owns the state",
                                     status="phase-1 core done"))
    html = render(model)
    assert '<header class="session-header">' in html
    assert '<div class="meta-strip">' in html
    # strip first, then title, then essence
    assert html.index("meta-strip") < html.index(f"<h1>{title}</h1>")
    assert html.index(f"<h1>{title}</h1>") < html.index("server owns the state")
    assert "your move" not in html and "move-text" not in html, \
        "the header carries no ask — that is the CTA card's job"
    assert '<span class="phase-chip ok">Building</span>' in html
    assert ">turn 46<" in html, "absolute turn in the strip"
    strip = html.split('<div class="meta-strip">')[1].split("</div>")[0]
    assert "phase-1 core done" not in strip, \
        "the strip carries short metadata only, never a sentence: " + strip
    assert len(strip) < 220, "the strip stays one quiet line: " + strip
    assert '<span class="meta-lineage"></span>' in html, "server fills the lineage slot"
    assert "<dt>what</dt>" not in html, "the four-row grid is gone"


def test_header_falls_back_to_the_chats_own_title():
    chat_title = "Fix the login flow"
    untitled = DashboardModel()
    assert f"<h1>{chat_title}</h1>" in render(untitled, chat_title)
    assert "<h1>Session</h1>" in render(untitled), "no fallback still renders the generic header"
    model_title = "Model-chosen title"
    titled = DashboardModel(title=model_title)
    assert f"<h1>{model_title}</h1>" in render(titled, chat_title), \
        "a model-set title must win over the fallback"


def test_the_line_under_the_title_prefers_essence_and_falls_back_to_status():
    both = DashboardModel(title="X", phase=Phase.review,
                          tldr=Tldr(essence="what we are building",
                                    status="PR #1905 in draft"))
    html = render(both)
    assert '<span class="phase-chip warn">Awaiting review</span>' in html
    assert '<p class="essence">what we are building</p>' in html
    assert "PR #1905 in draft" not in html, "one description line, not two"
    only_status = DashboardModel(title="X", tldr=Tldr(status="PR #1905 in draft"))
    assert '<p class="essence">PR #1905 in draft</p>' in render(only_status)


def test_a_bare_model_renders_the_phase_chip():
    html = render(DashboardModel(title="X", phase=Phase.planning))
    assert '<span class="phase-chip info">Planning</span>' in html


def test_links_render_as_chips_between_header_and_cta():
    m = DashboardModel(
        title="T",
        links=[
            models.LinkItem(id="l1", label="ENG-3345", url="https://linear.app/x/ENG-3345", kind="issue"),
            models.LinkItem(id="l2", label="claude/video-ingestion", kind="branch"),
        ],
        cta=[CtaItem(id="c1", text="an ask")],
    )
    html = render(m)
    assert html.index("</header>") < html.index('class="link-chips"') < html.index('card questions')
    assert '<a class="link-chip" href="https://linear.app/x/ENG-3345">' in html
    assert "🎫" in html and "🌿" in html
    assert '<span class="link-chip">🌿 <span class="kind">branch</span> claude/video-ingestion</span>' in html, \
        "a URL-less link renders as plain text, not an anchor"


def test_no_links_render_no_strip():
    assert "link-chips" not in render(DashboardModel(title="T"))


def test_last_turn_renders_atop_the_cta_card():
    m = DashboardModel(
        turn=9,
        last_turn=models.LastTurn(bullets=["shipped the thing", "tests green"], turn=9),
        cta=[CtaItem(id="c1", text="review the diff")],
    )
    html = render(m)
    card = html.split('<section class="card questions">')[1].split("</section>")[0]
    assert "shipped the thing" in card and "tests green" in card
    assert "· turn 9" in card
    assert card.index("shipped the thing") < card.index("review the diff"), \
        "the last-turn strip sits above the asks"
    assert 'class="last-turn-divider"' in card


def test_no_last_turn_renders_no_strip():
    html = render(DashboardModel(cta=[CtaItem(id="c1", text="an ask")]))
    assert "last-turn" not in html


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


def test_every_done_todo_renders_as_its_own_row():
    texts = ["alpha", "beta", "gamma", "lone done"]
    model = DashboardModel(todo=[
        TodoItem(id="t1", text=texts[0], status=TodoStatus.done),
        TodoItem(id="t2", text=texts[1], status=TodoStatus.done),
        TodoItem(id="t3", text=texts[2], status=TodoStatus.done),
        TodoItem(id="t4", text="current work", status=TodoStatus.active),
        TodoItem(id="t5", text=texts[3], status=TodoStatus.done),
    ])
    html = render(model)
    for text in texts:
        assert f'<li class="done"><span class="label">{text}</span></li>' in html, \
            f"done history row {text!r} must render whole"
    assert "3 done" not in html, "done runs are never collapsed into a summary line"
    assert '<li class="active checkable" data-item-id="t4">' in html


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
    assert ('<td class="ack-col"><button class="ack-btn" type="button">acknowledge</button>'
            '<button class="copy-btn" type="button" title="copy for the agent" '
            'data-copy="Dashboard heads-up (risk): chose upsert. Why: could dup. '
            'Where: fold.py">copy</button></td>') in html


def test_headsup_copy_text_stamps_turn_strips_html_and_ends_sentences():
    m = DashboardModel(turn=5, turn_base=10, headsup=[
        HeadsupItem(id="h1", sev=Sev.flag, what="<code>a &lt; b</code> looks wrong",
                    why="silently skips!", created_turn=2),
    ])
    assert ('data-copy="Dashboard heads-up (flag, raised turn 12): a &lt; b looks wrong. '
            'Why: silently skips!"') in render(m)


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




def test_todo_age_cells_state_created_and_done_turns():
    now_turn = 10
    m = DashboardModel(title="T", turn=now_turn, todo=[
        TodoItem(id="t1", text="open step", status=TodoStatus.open, created_turn=4),
        TodoItem(id="t2", text="done step", status=TodoStatus.done,
                 created_turn=2, done_turn=9),
        TodoItem(id="t3", text="legacy", status=TodoStatus.open),
    ])
    html = render(m)
    open_li = [ln for ln in html.splitlines() if "open step" in ln][0]
    assert 'title="created turn 4 · now turn 10">6 turns ago' in open_li, open_li
    done_li = [ln for ln in html.splitlines() if "done step" in ln][0]
    assert 'title="created turn 2 · done turn 9 · now turn 10">done 1 turn ago' in done_li, done_li
    legacy_li = [ln for ln in html.splitlines() if "legacy" in ln][0]
    assert 'class="age"' not in legacy_li, "unknown stamps show no age cell: " + legacy_li



def test_freeform_slots_are_wrapped_with_dismiss_chrome():
    live_body = '<section class="card free-form">live design</section>'
    dismissed_body = '<section class="card free-form">old sketch</section>'
    m = DashboardModel(title="T", freeform=[
        FreeformSlot(id="f1", html=live_body),
        FreeformSlot(id="f2", html=dismissed_body, dismissed_turn=3),
    ])
    html = render(m)
    assert '<div class="freeform-slot" data-item-id="f1">' in html
    assert live_body in html, "the body stays verbatim inside the wrapper"
    assert '<div class="freeform-slot dismissed" data-item-id="f2">' in html
    assert dismissed_body in html, "dismissed cards remain viewable history"
    assert html.count('button class="ff-dismiss"') == 2


def test_header_anchors_the_current_turn():
    m = DashboardModel(title="T", turn=18, turn_base=55)
    assert ">turn 73<" in render(m), "absolute turn = base + local"


def test_rows_carry_an_age_column_with_exact_turns_on_hover():
    now, base = 18, 55            # absolute now = 73
    m = DashboardModel(title="T", turn=now, turn_base=base,
        todo=[TodoItem(id="t1", text="fresh step", status=TodoStatus.open,
                       created_turn=17),
              TodoItem(id="t2", text="old step", status=TodoStatus.open,
                       created_turn=2),
              TodoItem(id="t3", text="closed step", status=TodoStatus.done,
                       created_turn=2, done_turn=16)],
        headsup=[HeadsupItem(id="h1", sev=Sev.note, what="w", why="y",
                             created_turn=4)],
        freeform=[FreeformSlot(id="f1", html="<section>x</section>",
                               changed_turn=12)])
    html = render(m)
    assert '<span class="age" title="created turn 72 · now turn 73">1 turn ago</span>' in html, html
    # The base shifts absolute labels; a difference of turns is unaffected.
    assert ">16 turns ago<" in html, "an old open step reports its age in turns"
    assert 'title="created turn 57 · done turn 71 · now turn 73">done 2 turns ago' in html, html
    assert 'title="raised turn 59 · now turn 73">14 turns ago' in html, "heads-up says raised"
    assert 'title="updated turn 67 · now turn 73">6 turns ago' in html, "freeform says updated"


def test_unknown_stamps_render_no_age_at_all():
    m = DashboardModel(title="T", turn=9, todo=[
        TodoItem(id="t1", text="legacy", status=TodoStatus.open)])
    html = render(m)
    row = [ln for ln in html.splitlines() if "legacy" in ln][0]
    assert 'class="age"' not in row, row


def test_a_fresh_item_reads_this_turn():
    m = DashboardModel(title="T", turn=9, todo=[
        TodoItem(id="t1", text="just added", status=TodoStatus.open, created_turn=9)])
    assert ">this turn<" in render(m)


def test_journey_off_renders_no_journey_card():
    m = DashboardModel(
        title="T",
        journey=[JourneyItem(id="j1", kind=JourneyKind.joint, what="w", why="y")],
    )
    assert 'class="card journey"' in render(m)
    assert 'class="card journey"' not in render(m, journey=False)


if __name__ == "__main__":
    run_module_tests(globals())
