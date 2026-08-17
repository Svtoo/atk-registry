"""Tests for the live app-wide notice set (notice_center.py).
Run: ../.venv/bin/python test_notice_center.py
"""

from notice_center import NoticeCenter
from testutil import run_module_tests


def test_a_raised_notice_appears_in_the_snapshot_with_its_detail():
    center = NoticeCenter()
    detail = "claude -p exited 1"
    center.raise_("account.signed_out", detail=detail)
    snap = center.snapshot()
    assert [n["code"] for n in snap["notices"]] == ["account.signed_out"]
    assert snap["notices"][0]["detail"] == detail
    assert snap["notices"][0]["at"] > 0


def test_raising_changes_the_generation_so_pages_know_to_repaint():
    center = NoticeCenter()
    before = center.snapshot()["generation"]
    center.raise_("account.signed_out")
    assert center.snapshot()["generation"] == before + 1


def test_re_raising_the_same_state_does_not_churn_the_generation():
    center = NoticeCenter()
    detail = "same failure"
    center.raise_("account.signed_out", detail=detail)
    generation = center.snapshot()["generation"]
    center.raise_("account.signed_out", detail=detail)
    assert center.snapshot()["generation"] == generation


def test_a_changed_detail_counts_as_a_change():
    center = NoticeCenter()
    center.raise_("account.signed_out", detail="first")
    generation = center.snapshot()["generation"]
    center.raise_("account.signed_out", detail="second")
    assert center.snapshot()["generation"] == generation + 1


def test_clearing_a_prefix_removes_the_whole_family():
    center = NoticeCenter()
    center.raise_("account.signed_out")
    center.raise_("account.check_pending")
    center.raise_("store.degraded")
    center.clear(prefix="account.")
    assert [n["code"] for n in center.snapshot()["notices"]] == ["store.degraded"]


def test_clearing_nothing_does_not_churn_the_generation():
    center = NoticeCenter()
    center.raise_("store.degraded")
    generation = center.snapshot()["generation"]
    center.clear(prefix="account.")
    assert center.snapshot()["generation"] == generation


def test_has_reports_whether_a_family_is_active():
    center = NoticeCenter()
    assert center.has("account.") is False
    center.raise_("account.signed_out")
    assert center.has("account.") is True


def test_only_one_probe_can_run_at_a_time():
    center = NoticeCenter()
    assert center.begin_probe() is True
    assert center.begin_probe() is False, "second claim while one is running"
    center.end_probe()


def test_a_finished_probe_blocks_re_probing_until_the_interval_passes():
    interval_s = 300.0
    center = NoticeCenter(probe_interval_s=interval_s)
    assert center.begin_probe() is True
    center.end_probe()
    assert center.begin_probe() is False, "too soon after the last probe"


def test_a_probe_can_run_again_once_the_interval_has_passed():
    center = NoticeCenter(probe_interval_s=0.0)
    assert center.begin_probe() is True
    center.end_probe()
    assert center.begin_probe() is True


if __name__ == "__main__":
    run_module_tests(globals())
