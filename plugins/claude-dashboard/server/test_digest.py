"""Tests for the agent digest (digest.py) — the compact, agent-facing
view of the model. Run: ../.venv/bin/python test_digest.py
"""

from digest import build_digest
from models import (
    JOURNEY_MAX, CtaItem, DashboardModel, FreeformSlot, HeadsupItem, JourneyItem,
    Tldr, TodoItem, JourneyKind, Phase, Sev, TodoStatus,
)
from testutil import run_module_tests


def test_digest_flags_journey_over_cap_for_agent_driven_fold():
    beats = [JourneyItem(id=f"j{i}", kind=JourneyKind.agent, what=f"beat {i}", why="w", turn=1)
             for i in range(JOURNEY_MAX + 2)]
    digest = build_digest(DashboardModel(turn=1, journey=beats))
    assert "OVER CAP" in digest, "an over-cap journey must flag the agent to fold"
    assert "journey.fold" in digest, "the digest must name the op the agent should emit"

    under = build_digest(DashboardModel(turn=1, journey=beats[:JOURNEY_MAX]))
    assert "OVER CAP" not in under, "a within-cap journey must not flag"


def test_digest_lists_every_section_with_ids_and_tldr():
    model = DashboardModel(
        title="T", turn=5, phase=Phase.building,
        tldr=Tldr(essence="what-line", status="where-line", next="move-line"),
        cta=[CtaItem(id="c1", text="a blocker", changed_turn=5, reason="new")],
        todo=[TodoItem(id="t1", text="a task", status=TodoStatus.open, changed_turn=2, reason="start")],
        headsup=[HeadsupItem(id="h1", sev=Sev.risk, what="w", why="y", where="z", changed_turn=4, reason="r")],
        journey=[JourneyItem(id="j1", kind=JourneyKind.agent, what="d", why="rr", turn=5)],
        freeform=[FreeformSlot(id="f1", html="<section>x</section>", hash="abc123", changed_turn=3, reason="arch")],
    )
    digest = build_digest(model)
    for token in ["c1", "t1", "h1", "j1", "f1", "what-line", "where-line", "move-line"]:
        assert token in digest, token


def test_digest_shows_freeform_body_in_full():
    # Freeform is sticky: the agent must see the current body to know it is still
    # correct (leave it alone) and to edit it faithfully when the design changes.
    marker = "the-design-diagram-goes-here"
    body = f"<section class='card free-form'>{marker}</section>"
    model = DashboardModel(turn=1, freeform=[
        FreeformSlot(id="f1", html=body, hash="deadbeef", changed_turn=1, reason="arch"),
    ])
    digest = build_digest(model)
    assert marker in digest, "the freeform body must be shown in full so the agent can leave it or edit it"
    assert "f1" in digest and "arch" in digest, "the id and reason still frame the body"


def test_digest_renders_change_motion():
    model = DashboardModel(turn=10, todo=[
        TodoItem(id="t1", text="old", status=TodoStatus.done, changed_turn=3, reason="finished early"),
        TodoItem(id="t2", text="fresh", status=TodoStatus.active, changed_turn=10, reason="just started"),
    ])
    digest = build_digest(model)
    assert "7t ago: finished early" in digest, "turns-ago motion must render"
    assert "now: just started" in digest, "a same-turn change reads as 'now'"


def test_digest_measures_ago_against_the_current_turn():
    # Regens can skip turns: the state's own turn lags the conversation. The
    # motion must be measured from the CURRENT turn, not the stale state turn.
    state_turn, current_turn = 10, 14
    model = DashboardModel(turn=state_turn, todo=[
        TodoItem(id="t1", text="x", status=TodoStatus.active, changed_turn=10, reason="started"),
    ])
    digest = build_digest(model, now_turn=current_turn)
    assert f"{current_turn - 10}t ago: started" in digest
    assert f"as of conversation turn {state_turn}" in digest, "the header keeps the state's own turn"


def test_digest_shows_heads_up_in_full():
    items = [HeadsupItem(id=f"h{i}", sev=Sev.note, what=f"w{i}", why="y", changed_turn=1, reason="r")
             for i in range(1, 13)]
    digest = build_digest(DashboardModel(turn=1, headsup=items))
    for i in range(1, 13):
        assert f"h{i} " in digest, f"h{i} must appear — heads-up is fed in full to prevent duplicates"


if __name__ == "__main__":
    run_module_tests(globals())
