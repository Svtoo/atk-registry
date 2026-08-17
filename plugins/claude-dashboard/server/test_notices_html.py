"""Tests for notice markup (notices_html.py): the one renderer, escaping, and
the shape every page's notice region relies on.
Run: ../.venv/bin/python test_notices_html.py
"""

import re

from notices import envelope
from notices_html import render_client_templates, render_list, render_one
from testutil import run_module_tests

HOSTILE = '<script>alert("x")</script>'


def _one(code, **kw):
    return render_one(envelope(code, **kw))


# ─── the region ────────────────────────────────────────────────────────

def test_an_empty_list_renders_nothing_so_the_region_collapses():
    assert render_list([]) == ""


def test_a_list_wraps_its_entries_in_one_ordered_list():
    html = render_list([envelope("account.signed_out"), envelope("net.server_down")])
    assert html.count('<ol class="notices__list">') == 1
    assert html.count("<li class=\"notice ") == 2


def test_a_group_label_is_shown_only_when_asked_for():
    group = "Dashboard updates"
    assert group in render_list([envelope("rebuild.timeout")], group_label=group)
    assert "notices__group" not in render_list([envelope("rebuild.timeout")])


# ─── one card ──────────────────────────────────────────────────────────

def test_a_card_carries_its_code_and_severity_for_styling_and_tests():
    code = "account.signed_out"
    html = _one(code)
    assert f'data-code="{code}"' in html
    assert 'class="notice notice--blocked"' in html


def test_every_severity_has_its_own_modifier_class():
    seen = {}
    for code in ("account.signed_out", "rebuild.timeout", "page.internal",
                 "chat.pending"):
        html = _one(code)
        match = re.search(r'class="notice (notice--[a-z]+)"', html)
        assert match, code
        seen[code] = match.group(1)
    assert len(set(seen.values())) == 4, seen


def test_a_card_shows_the_title_and_what_it_means():
    from notices import catalog
    n = catalog()["account.signed_out"]
    html = _one(n.code)
    assert n.title in html
    assert n.what in html


def test_a_step_with_a_command_renders_it_beside_a_copy_button():
    sign_in_command = "claude auth login"
    html = _one("account.signed_out")
    assert f"<code>{sign_in_command}</code>" in html
    assert f'data-copy="{sign_in_command}"' in html


def test_a_step_with_a_link_renders_an_anchor_with_its_own_label():
    html = _one("account.model_denied")
    assert '<a class="notice__link" href="/settings"' in html
    assert ">Settings</a>" in html


def test_a_step_with_neither_a_command_nor_a_link_renders_no_empty_control():
    html = _one("net.page_failed")
    assert "notice__cmd" not in html
    assert "notice__link" not in html
    assert "<a " not in html


def test_a_notice_with_no_steps_renders_no_step_list():
    html = _one("chat.pending")
    assert "notice__steps" not in html


# ─── dismissing ────────────────────────────────────────────────────────

def test_a_notice_the_person_may_dismiss_gets_a_button():
    html = _one("rebuild.timeout")
    assert "notice__dismiss" in html


def test_a_notice_the_person_may_not_dismiss_gets_no_button():
    html = _one("account.signed_out")
    assert "notice__dismiss" not in html


# ─── the collapsed extras ──────────────────────────────────────────────

def test_the_long_form_answer_is_collapsed_behind_a_summary():
    html = _one("account.signed_out")
    assert 'class="notice__explain"' in html
    assert "<summary>" in html


def test_raw_text_is_only_ever_reachable_under_technical_detail():
    raw = "claude -p exited 1 after 3.0s"
    html = _one("rebuild.failed", detail=raw)
    detail_start = html.index('class="notice__detail"')
    assert raw in html[detail_start:], "raw text belongs in the collapsed block"
    assert raw not in html[:detail_start], "raw text must not be the headline"


def test_a_notice_without_raw_text_renders_no_detail_block():
    assert "notice__detail" not in _one("chat.gone")


def test_a_reportable_notice_renders_its_report_actions():
    html = _one("rebuild.too_large")
    assert "Report it on GitHub" in html
    assert "Copy diagnostics" in html


# ─── escaping ──────────────────────────────────────────────────────────

def test_raw_text_from_the_cli_cannot_inject_markup():
    html = _one("rebuild.failed", detail=HOSTILE)
    assert HOSTILE not in html
    assert "&lt;script&gt;" in html


def test_a_server_supplied_reason_cannot_inject_markup():
    html = render_one(envelope("settings.rejected", facts={"reason": HOSTILE}))
    assert HOSTILE not in html
    assert "&lt;script&gt;" in html


def test_a_measurement_value_cannot_inject_markup():
    html = _one("rebuild.too_large", measurements={"model": HOSTILE})
    assert HOSTILE not in html


# ─── the templates the browser clones when we are unreachable ──────────

def test_client_templates_ship_the_markup_for_an_offline_page():
    offline_code = "net.server_down"
    html = render_client_templates([offline_code])
    assert f'<template data-notice-code="{offline_code}">' in html
    assert "atk start claude-dashboard" in html


def test_client_templates_render_nothing_for_an_empty_list():
    assert render_client_templates([]) == ""


if __name__ == "__main__":
    run_module_tests(globals())
