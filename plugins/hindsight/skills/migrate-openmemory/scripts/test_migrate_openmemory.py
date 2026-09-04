#!/usr/bin/env python3
"""Tests for the parts of the migration that decide where a memory lands.

Run: python3 scripts/test_migrate_openmemory.py
"""
import importlib.util
import json
import pathlib
import tempfile

spec = importlib.util.spec_from_file_location(
    "migrate_openmemory", pathlib.Path(__file__).with_name("migrate_openmemory.py"))
mo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mo)


def row(source_id, tags):
    return {"id": source_id, "content": "text", "tags": tags, "created_at": 1771437356882}


def write_plan(groups, precedence=None):
    plan = {
        "rows_without_project_tag": 0,
        "all_tags": sorted(t for g in groups for t in g["tags"]),
        "groups": groups,
    }
    if precedence is not None:
        plan["precedence"] = precedence
    path = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False).name
    with open(path, "w") as fh:
        json.dump(plan, fh)
    return path


def test_one_tag_resolves_to_its_target():
    mapping = {"project-atk": "project:atk"}
    memory = row("m1", ["project-atk"])

    actual = mo.resolve_targets(memory, mapping, [])

    assert actual == ["project:atk"]


def test_untargeted_tag_resolves_to_nothing():
    mapping = {"project-personal": None}
    memory = row("m2", ["project-personal"])

    actual = mo.resolve_targets(memory, mapping, [])

    assert actual == []


def test_competing_targets_are_both_returned_when_no_precedence():
    mapping = {"project-atk": "project:atk", "project-atk-registry": "project:atk-registry"}
    memory = row("m3", ["project-atk", "project-atk-registry"])

    actual = mo.resolve_targets(memory, mapping, [])

    assert actual == ["project:atk", "project:atk-registry"]


def test_precedence_picks_the_earlier_target():
    mapping = {"project-atk": "project:atk", "project-atk-registry": "project:atk-registry"}
    memory = row("m4", ["project-atk", "project-atk-registry"])
    precedence = ["atk-registry", "atk"]

    actual = mo.resolve_targets(memory, mapping, precedence)

    assert actual == ["project:atk-registry"]


def test_precedence_only_covering_one_side_still_leaves_the_conflict():
    # A precedence naming just one of the two competitors is ambiguous: it says
    # nothing about whether the unnamed one outranks it.
    mapping = {"project-atk": "project:atk", "project-obsidian": "project:obsidian"}
    memory = row("m5", ["project-atk", "project-obsidian"])
    precedence = ["atk"]

    actual = mo.resolve_targets(memory, mapping, precedence)

    assert actual == ["project:atk", "project:obsidian"]


def test_conflict_groups_counts_each_competing_combination():
    mapping = {"project-atk": "project:atk", "project-obsidian": "project:obsidian",
               "project-micro": "project:micro"}
    rows = [row("m6", ["project-atk", "project-obsidian"]),
            row("m7", ["project-atk", "project-obsidian"]),
            row("m8", ["project-atk", "project-micro"]),
            row("m9", ["project-atk"])]

    actual = mo.conflict_groups(rows, mapping, [])

    assert sorted(actual) == [("project:atk", "project:micro"),
                              ("project:atk", "project:obsidian")]
    assert actual[("project:atk", "project:obsidian")]["count"] == 2
    assert actual[("project:atk", "project:micro")]["count"] == 1
    assert actual[("project:atk", "project:micro")]["sample"] == "m8"


def test_conflict_groups_reports_the_tags_that_produced_the_clash():
    mapping = {"project-atk": "project:atk", "project-obsidian": "project:obsidian"}
    rows = [row("m10", ["project-atk", "project-obsidian"])]

    actual = mo.conflict_groups(rows, mapping, [])

    assert actual[("project:atk", "project:obsidian")]["tags"] == [
        "project-atk", "project-obsidian"]


def test_precedence_removes_the_conflict_from_the_report():
    mapping = {"project-atk": "project:atk", "project-obsidian": "project:obsidian"}
    rows = [row("m11", ["project-atk", "project-obsidian"])]

    actual = mo.conflict_groups(rows, mapping, ["obsidian", "atk"])

    assert actual == {}


def test_plan_rejects_a_precedence_entry_that_is_not_a_target():
    groups = [{"tags": ["project-atk"], "memories": 1, "target": "atk"},
              {"tags": ["project-obsidian"], "memories": 1, "target": "obsidian"}]
    path = write_plan(groups, precedence=["atk", "obsidain"])  # typo

    try:
        mo.load_plan(path)
    except SystemExit:
        return
    raise AssertionError("load_plan accepted a precedence entry naming no group target")


def test_plan_accepts_a_precedence_of_real_targets():
    groups = [{"tags": ["project-atk"], "memories": 1, "target": "atk"},
              {"tags": ["project-obsidian"], "memories": 1, "target": "obsidian"}]
    path = write_plan(groups, precedence=["obsidian", "atk"])

    actual = mo.load_plan(path)

    assert actual["precedence"] == ["obsidian", "atk"]


def test_plan_without_precedence_reads_as_empty():
    groups = [{"tags": ["project-atk"], "memories": 1, "target": "atk"}]
    path = write_plan(groups)

    actual = mo.load_plan(path)

    assert actual["precedence"] == []


def test_rows_in_scope_honours_a_limit():
    rows = [row("m12", []), row("m13", []), row("m14", [])]
    limit = 2

    actual = mo.rows_in_scope(rows, limit)

    assert [r["id"] for r in actual] == ["m12", "m13"]


def test_rows_in_scope_without_a_limit_is_everything():
    rows = [row("m15", []), row("m16", [])]

    actual = mo.rows_in_scope(rows, 0)

    assert [r["id"] for r in actual] == ["m15", "m16"]



def test_a_plan_with_every_target_blank_reads_as_unanswered():
    groups = [{"tags": ["project-atk"], "memories": 1, "target": ""},
              {"tags": ["project-obsidian"], "memories": 1, "target": ""}]

    actual = mo.all_untagged({"groups": groups})

    assert actual is True


def test_a_plan_with_one_real_target_is_answered():
    groups = [{"tags": ["project-atk"], "memories": 1, "target": "atk"},
              {"tags": ["project-personal"], "memories": 1, "target": ""}]

    actual = mo.all_untagged({"groups": groups})

    assert actual is False


if __name__ == "__main__":
    tests = [(name, fn) for name, fn in sorted(globals().items()) if name.startswith("test_")]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as exc:  # noqa: BLE001 - a test runner reports every failure
            failed += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)
