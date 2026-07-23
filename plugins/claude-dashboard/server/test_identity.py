"""Tests for identity.py (transcript-derived project identity) and its
wiring into serve.py grouping. Pure file parsing, no git subprocess.
Run: ../.venv/bin/python test_identity.py
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

# ─── fake projects root (must exist before serve import) ───────────────
#
# Layout mirrors the real-world shapes the design must handle:
#   repo/               a git repo (".git" directory)
#   elsewhere/wt1/      a linked worktree OUTSIDE the repo (".git" pointer file)
#   plain/              a non-git folder
# and transcript slugs for: the repo, the worktree, a session with a dead
# cwd in a worktree container, and a --claude-worktrees- marker slug.

_tmp = Path(tempfile.mkdtemp(prefix="ccd-identity-test-"))

REPO = _tmp / "work" / "repo"
(REPO / ".git" / "worktrees" / "wt1").mkdir(parents=True)
WT1 = _tmp / "work" / "container" / "wt1"
WT1.mkdir(parents=True)
(WT1 / ".git").write_text(f"gitdir: {REPO}/.git/worktrees/wt1\n")
WT2 = _tmp / "work" / "container" / "wt2"
WT2.mkdir(parents=True)
(WT2 / ".git").write_text(f"gitdir: {REPO}/.git/worktrees/wt2\n")
PLAIN = _tmp / "work" / "plain"
PLAIN.mkdir(parents=True)
DEAD_WT = _tmp / "work" / "container" / "gone-wt"  # never created

PROJECTS = _tmp / "projects"
PROJECTS.mkdir()
os.environ["CLAUDE_PROJECTS_DIR"] = str(PROJECTS)

UUIDS = [f"00000000-0000-4000-8000-00000000000{i}" for i in range(10)]


def _write_session(slug: str, uuid: str, cwd: str, branch: str = "main") -> Path:
    proj = PROJECTS / slug
    proj.mkdir(exist_ok=True)
    jsonl = proj / f"{uuid}.jsonl"
    lines = [
        {"type": "queue-operation", "op": "x"},
        {"type": "ai-title", "aiTitle": "t"},
        {"type": "user", "cwd": "/decoy/sidechain", "gitBranch": "decoy",
         "isSidechain": True, "message": {"content": "side"}},
        {"type": "user", "cwd": cwd, "gitBranch": branch,
         "message": {"content": "hi"}},
        {"type": "assistant", "cwd": cwd, "gitBranch": branch,
         "message": {"content": []}},
    ]
    jsonl.write_text("\n".join(json.dumps(d) for d in lines) + "\n")
    return jsonl


import identity  # noqa: E402
from identity import (  # noqa: E402
    rescue_dead,
    resolve_root,
    session_anchor,
    slug_for_path,
)

REPO_SLUG = slug_for_path(str(REPO))
WT1_SLUG = slug_for_path(str(WT1))

S_REPO = _write_session(REPO_SLUG, UUIDS[0], str(REPO), branch="develop")
S_REPO_SUB = _write_session(REPO_SLUG, UUIDS[1], str(REPO / "sub" / "dir"))
S_WT1 = _write_session(WT1_SLUG, UUIDS[2], str(WT1), branch="feature/x")
S_DEAD = _write_session(REPO_SLUG, UUIDS[3], str(DEAD_WT), branch="claude/gone")
(REPO / "sub" / "dir").mkdir(parents=True)

import serve  # noqa: E402


# ─── session_anchor ────────────────────────────────────────────────────

def test_anchor_skips_meta_and_sidechain_lines():
    expected_cwd = str(REPO)
    expected_branch = "develop"
    anchor = session_anchor(S_REPO)
    assert anchor["cwd"] == expected_cwd, anchor
    assert anchor["gitBranch"] == expected_branch, anchor


def test_anchor_gives_up_after_scan_bound():
    proj = PROJECTS / REPO_SLUG
    jsonl = proj / f"{UUIDS[4]}.jsonl"
    filler = json.dumps({"type": "queue-operation"})
    tail = json.dumps({"type": "user", "cwd": str(REPO)})
    jsonl.write_text("\n".join([filler] * identity.ANCHOR_SCAN_LINES + [tail]) + "\n")
    try:
        anchor = session_anchor(jsonl)
        assert anchor["cwd"] is None, anchor
    finally:
        jsonl.unlink()


def test_anchor_on_missing_file_is_empty_not_an_error():
    anchor = session_anchor(PROJECTS / "nope" / "nope.jsonl")
    assert anchor == {"cwd": None, "gitBranch": None}


# ─── resolve_root: live directories ────────────────────────────────────

def test_repo_cwd_resolves_to_itself():
    r = resolve_root(str(REPO))
    assert r == {"root": str(REPO), "kind": "repo",
                 "isWorktree": False, "worktreeDir": None}, r


def test_repo_subdir_resolves_to_the_repo():
    r = resolve_root(str(REPO / "sub" / "dir"))
    assert r["root"] == str(REPO), r
    assert r["kind"] == "repo", r


def test_worktree_outside_the_repo_resolves_to_the_main_repo():
    r = resolve_root(str(WT1))
    assert r["root"] == str(REPO), r
    assert r["isWorktree"] is True, r
    assert r["worktreeDir"] == str(WT1), r


def test_worktree_subdir_still_resolves_to_the_main_repo():
    sub = WT1 / "apps" / "api"
    sub.mkdir(parents=True, exist_ok=True)
    r = resolve_root(str(sub))
    assert r["root"] == str(REPO), r
    assert r["worktreeDir"] == str(WT1), r


def test_gitdir_pointer_with_spaces_survives():
    repo_sp = _tmp / "My Drive" / "repo sp"
    (repo_sp / ".git" / "worktrees" / "wt s").mkdir(parents=True)
    wt_sp = _tmp / "My Drive" / "wt s"
    wt_sp.mkdir(parents=True)
    (wt_sp / ".git").write_text(f"gitdir: {repo_sp}/.git/worktrees/wt s\n")
    r = resolve_root(str(wt_sp))
    assert r["root"] == str(repo_sp), r


def test_submodule_pointer_is_its_own_project():
    sub = _tmp / "work" / "repo" / "vendored"
    sub.mkdir(parents=True, exist_ok=True)
    (sub / ".git").write_text(f"gitdir: {REPO}/.git/modules/vendored\n")
    r = resolve_root(str(sub))
    assert r["root"] == str(sub), r
    assert r["isWorktree"] is False, r


def test_non_git_dir_is_its_own_project():
    r = resolve_root(str(PLAIN))
    assert r == {"root": str(PLAIN), "kind": "dir",
                 "isWorktree": False, "worktreeDir": None}, r


def test_dead_dir_resolves_to_none():
    assert resolve_root(str(DEAD_WT)) is None


def test_garbage_cwd_is_rejected():
    for bad in ("", "relative/path", "a\nb", "/x\x00y", "/" + "a" * 5000):
        assert resolve_root(bad) is None, f"accepted {bad!r}"


# ─── rescue_dead: fallbacks for deleted directories ────────────────────

def _live_index() -> dict:
    """cwd -> resolve_root result for the live session cwds in the fixture."""
    idx = {}
    for cwd in (str(REPO), str(WT1), str(WT2)):
        idx[cwd] = resolve_root(cwd)
    return idx


def test_dead_claude_worktree_is_rescued_by_its_ancestor_repo():
    dead = str(REPO / ".claude" / "worktrees" / "removed-wt")
    root = rescue_dead(dead, {}, home=str(_tmp / "nohome"), temp_prefixes=())
    assert root == str(REPO), root


def test_ancestor_rescue_never_adopts_the_home_repo():
    home = _tmp / "home"
    (home / ".git").mkdir(parents=True)
    dead = str(home / "deleted-project")
    root = rescue_dead(dead, {}, home=str(home), temp_prefixes=())
    assert root is None, root


def test_dead_sibling_in_agreeing_worktree_container_is_rescued():
    # Two live worktrees of REPO share the container; the dead one joins them.
    root = rescue_dead(str(DEAD_WT), _live_index(),
                       home=str(_tmp / "nohome"), temp_prefixes=())
    assert root == str(REPO), root


def test_single_sibling_needs_a_container_named_after_the_repo():
    container = _tmp / "work" / "repo"  # container basename == repo basename
    lone = {str(WT1): dict(resolve_root(str(WT1)), worktreeDir=str(container / "only-wt"))}
    dead = str(container / "gone")
    root = rescue_dead(dead, lone, home=str(_tmp / "nohome"), temp_prefixes=())
    assert root == str(REPO), root

    oddly_named = {str(WT1): resolve_root(str(WT1))}  # container "container" != "repo"
    dead2 = str(DEAD_WT)
    root2 = rescue_dead(dead2, oddly_named, home=str(_tmp / "nohome"), temp_prefixes=())
    assert root2 is None, root2


def test_dead_subdir_of_a_removed_worktree_is_rescued_too():
    dead_subdir = str(DEAD_WT / "apps" / "api")
    root = rescue_dead(dead_subdir, _live_index(),
                       home=str(_tmp / "nohome"), temp_prefixes=())
    assert root == str(REPO), root


def test_sibling_rescue_refuses_temp_containers():
    root = rescue_dead(str(DEAD_WT), _live_index(),
                       home=str(_tmp / "nohome"),
                       temp_prefixes=(str(DEAD_WT.parent),))
    assert root is None, root


def test_sibling_rescue_refuses_disagreeing_siblings():
    other_repo = _tmp / "work" / "other"
    (other_repo / ".git").mkdir(parents=True)
    idx = _live_index()
    wt2 = dict(idx[str(WT2)])
    wt2["root"] = str(other_repo)
    idx[str(WT2)] = wt2
    root = rescue_dead(str(DEAD_WT), idx,
                       home=str(_tmp / "nohome"), temp_prefixes=())
    assert root is None, root


# ─── serve.py wiring: grouping, labels, sessions aggregation ───────────

def test_landing_folds_the_worktree_slug_under_the_repo_card():
    cards = serve.list_projects()
    by_label = {c["label"]: c for c in cards}
    assert "repo" in by_label, sorted(by_label)
    card = by_label["repo"]
    # repo slug sessions (2 live + 1 dead-rescued) + worktree slug session
    expected_chats = 4
    assert card["chatCount"] == expected_chats, card
    assert card["hash"] == REPO_SLUG, card
    member_hashes = {w["hash"] for w in card["worktrees"]}
    assert WT1_SLUG in member_hashes, card["worktrees"]


def test_landing_card_shows_the_real_root_path():
    cards = serve.list_projects()
    card = next(c for c in cards if c["label"] == "repo")
    assert card["rootPath"] == str(REPO), card


def test_plain_dir_slug_stays_its_own_card():
    slug = slug_for_path(str(PLAIN))
    _write_session(slug, UUIDS[5], str(PLAIN))
    serve._GROUPS_CACHE["at"] = 0.0
    try:
        cards = serve.list_projects()
        labels = [c["label"] for c in cards]
        assert "plain" in labels, labels
    finally:
        (PROJECTS / slug / f"{UUIDS[5]}.jsonl").unlink()
        serve._GROUPS_CACHE["at"] = 0.0


def test_sessions_page_aggregates_all_group_members():
    rows = serve.list_sessions(REPO_SLUG)
    uuids = {r["uuid"] for r in rows}
    assert UUIDS[2] in uuids, "worktree-slug session missing from the repo page"
    assert UUIDS[3] in uuids, "dead-worktree session missing from the repo page"


def test_worktree_session_is_tagged_with_its_branch():
    rows = serve.list_sessions(REPO_SLUG)
    wt_row = next(r for r in rows if r["uuid"] == UUIDS[2])
    assert wt_row["worktreeName"] == "feature/x", wt_row
    main_row = next(r for r in rows if r["uuid"] == UUIDS[0])
    assert main_row["worktreeName"] is None, main_row


def test_projects_payload_keeps_the_legacy_shape():
    card = serve.list_projects()[0]
    for key in ("hash", "label", "chatCount", "withDashboards",
                "lastActivity", "lastActivityIso", "worktrees"):
        assert key in card, f"missing {key}: {sorted(card)}"


def test_stats_rows_are_rebucketed_with_group_labels():
    rows = [
        {"project": REPO_SLUG, "regens": 3, "avg_wall_s": 10.0,
         "failed": 1, "superseded": 0, "cost_usd": 0.30},
        {"project": WT1_SLUG, "regens": 1, "avg_wall_s": 30.0,
         "failed": 0, "superseded": 1, "cost_usd": 0.10},
        {"project": "-gone-slug", "regens": 2, "avg_wall_s": 5.0,
         "failed": 0, "superseded": 0, "cost_usd": 0.05},
    ]
    out = serve.rebucket_stats_projects(rows)
    merged = next(r for r in out if r["label"] == "repo")
    assert merged["regens"] == 4, merged
    assert merged["failed"] == 1 and merged["superseded"] == 1, merged
    assert abs(merged["cost_usd"] - 0.40) < 1e-9, merged
    expected_avg = (10.0 * 3 + 30.0 * 1) / 4
    assert abs(merged["avg_wall_s"] - expected_avg) < 1e-9, merged
    gone = next(r for r in out if r["project"] == "-gone-slug")
    assert gone["label"] == "slug", gone  # today's last-segment fallback


def test_dead_unrescuable_card_is_labeled_by_its_real_folder_name():
    dead = _tmp / "work" / "renamed_away"  # never created; rescue finds nothing
    slug = slug_for_path(str(dead))
    _write_session(slug, UUIDS[6], str(dead))
    serve._GROUPS_CACHE["at"] = 0.0
    try:
        cards = serve.list_projects()
        labels = [c["label"] for c in cards]
        assert "renamed_away" in labels, labels
        assert "away" not in labels, labels  # the slug's last dash-segment
        card = next(c for c in cards if c["label"] == "renamed_away")
        assert card["rootPath"] == str(dead), card  # the remembered real path
    finally:
        (PROJECTS / slug / f"{UUIDS[6]}.jsonl").unlink()
        serve._GROUPS_CACHE["at"] = 0.0


def test_stats_slug_with_only_subagent_transcripts_joins_its_group():
    # Mirrors real data: a slug dir left behind by subagent spawns has no
    # top-level chat, but its subagent transcripts still carry the cwd.
    slug = slug_for_path(str(WT1)) + "-ghost"
    subdir = PROJECTS / slug / UUIDS[7] / "subagents" / "workflows" / "wf_x"
    subdir.mkdir(parents=True)
    (subdir / "agent-1.jsonl").write_text(json.dumps(
        {"type": "user", "cwd": str(WT1), "isSidechain": True,
         "message": {"content": "sub"}}) + "\n")
    serve._GROUPS_CACHE["at"] = 0.0
    try:
        rows = [{"project": slug, "regens": 5, "avg_wall_s": 1.0,
                 "failed": 0, "superseded": 0, "cost_usd": 0.50}]
        out = serve.rebucket_stats_projects(rows)
        assert len(out) == 1, out
        assert out[0]["label"] == "repo", out
    finally:
        import shutil
        shutil.rmtree(PROJECTS / slug)
        serve._GROUPS_CACHE["at"] = 0.0


if __name__ == "__main__":
    from testutil import run_module_tests
    run_module_tests(globals())
