"""Tests for lineage.py — which chat a session continues from.

A resumed or forked chat replays its parent's events verbatim, so shared
event uuids are the only signal used; timing and app-private files are not.
Run: ../.venv/bin/python test_lineage.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from lineage import LineageIndex, find_parent
from testutil import run_module_tests


def _write(dir_path: Path, session: str, events: list) -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    p = dir_path / f"{session}.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    return p


def _turn(uuid: str, text: str = "hi") -> dict:
    return {"type": "user", "uuid": uuid, "cwd": "/tmp",
            "message": {"content": text}, "timestamp": "2026-07-29T01:00:00.000Z"}


def _fixture() -> Path:
    return Path(tempfile.mkdtemp(prefix="ccd-lineage-"))


PARENT = "11111111-1111-4111-8111-111111111111"
CHILD = "22222222-2222-4222-8222-222222222222"
OTHER = "33333333-3333-4333-8333-333333333333"


def test_child_replaying_parent_events_finds_its_parent():
    proj = _fixture()
    shared = [_turn(f"u{i}") for i in range(6)]
    _write(proj, PARENT, shared + [_turn("p-tail")])
    _write(proj, CHILD, shared + [_turn("c-fresh")])
    assert find_parent(proj / f"{CHILD}.jsonl") == PARENT


def test_a_chat_that_shares_nothing_has_no_parent():
    proj = _fixture()
    _write(proj, PARENT, [_turn(f"a{i}") for i in range(6)])
    _write(proj, CHILD, [_turn(f"b{i}") for i in range(6)])
    assert find_parent(proj / f"{CHILD}.jsonl") is None


def test_the_parent_is_the_file_sharing_the_most_events():
    proj = _fixture()
    common = [_turn(f"u{i}") for i in range(4)]
    _write(proj, OTHER, common[:2])                       # a shallow ancestor
    _write(proj, PARENT, common + [_turn(f"m{i}") for i in range(4)])
    _write(proj, CHILD, common + [_turn(f"m{i}") for i in range(4)] + [_turn("new")])
    assert find_parent(proj / f"{CHILD}.jsonl") == PARENT


def test_a_parent_never_points_at_its_own_child():
    proj = _fixture()
    shared = [_turn(f"u{i}") for i in range(6)]
    _write(proj, PARENT, shared)
    _write(proj, CHILD, shared + [_turn("c-fresh")])
    # The child holds every parent event, but lineage runs one way: the file
    # that carries strictly more of the shared history is the child.
    assert find_parent(proj / f"{PARENT}.jsonl") is None


def test_incidental_overlap_below_the_floor_is_not_lineage():
    proj = _fixture()
    _write(proj, PARENT, [_turn(f"u{i}") for i in range(50)])
    _write(proj, CHILD, [_turn("u0")] + [_turn(f"c{i}") for i in range(40)])
    assert find_parent(proj / f"{CHILD}.jsonl") is None


def test_index_is_reused_until_a_transcript_changes():
    proj = _fixture()
    shared = [_turn(f"u{i}") for i in range(6)]
    _write(proj, PARENT, shared)
    child_path = _write(proj, CHILD, shared + [_turn("c1")])
    idx = LineageIndex()
    assert idx.parent_of(child_path) == PARENT
    scans = idx.scan_count
    assert idx.parent_of(child_path) == PARENT
    assert idx.scan_count == scans, "an unchanged tree must not be rescanned"
    _write(proj, CHILD, shared + [_turn("c1"), _turn("c2")])
    idx.parent_of(child_path)
    assert idx.scan_count > scans, "a changed transcript invalidates the index"


def test_missing_or_empty_transcript_is_not_an_error():
    proj = _fixture()
    assert find_parent(proj / "nope.jsonl") is None
    empty = _write(proj, CHILD, [])
    assert find_parent(empty) is None


def test_real_corpus_fork_and_resume_resolve_to_their_parents():
    """The two known real cases: a deliberate fork and a resume."""
    root = Path.home() / ".claude" / "projects"
    cases = [
        ("-Users-user--atk",
         "979d92f1-33a5-4f5c-b0b7-371c2b905f56",
         "6edf1f5a-2e61-4f44-8bbc-3ecffdf2e5b1"),
        ("-Users-user-project-eval-planning",
         "b9fd7b87-8ad8-466b-a76c-5d7a4ede666c",
         "f5e229a8-0919-4817-be49-c161929195c2"),
    ]
    checked = 0
    for slug, child, expected_parent in cases:
        p = root / slug / f"{child}.jsonl"
        if not p.is_file() or not (root / slug / f"{expected_parent}.jsonl").is_file():
            continue          # corpus-dependent; skip when either side is absent
        assert find_parent(p) == expected_parent, f"{child} -> {find_parent(p)}"
        checked += 1
    print(f"    (corpus cases checked: {checked}/2)")


if __name__ == "__main__":
    run_module_tests(globals())
