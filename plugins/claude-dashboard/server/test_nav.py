"""Tests for navigation rendering (serve.py SECTIONS, _nav_items, _breadcrumb):
exactly one menu entry is current, and the breadcrumb reflects the real
hierarchy. Run: ../.venv/bin/python test_nav.py
"""

from serve import SECTIONS, _breadcrumb, _nav_items
from testutil import run_module_tests

SECTION_KEYS = [key for key, _, _ in SECTIONS]


def _marked(html: str) -> int:
    """How many menu entries carry the current-page class."""
    return html.count('class="appmenu-item on"')


# ─── the menu ──────────────────────────────────────────────────────────

def test_every_section_renders_an_entry():
    html = _nav_items("projects")
    for _, label, href in SECTIONS:
        assert f'>{label}</a>' in html, f"{label} is missing from the menu"
        assert f'href="{href}"' in html, f"{href} is missing from the menu"


def test_exactly_one_entry_is_current_for_each_section():
    for key in SECTION_KEYS:
        html = _nav_items(key)
        assert _marked(html) == 1, f"section {key} marked {_marked(html)} entries, expected 1"


def test_the_current_entry_is_the_right_one():
    html = _nav_items("settings")
    assert '<a role="menuitem" class="appmenu-item on" href="/settings">Settings</a>' in html, html
    assert 'class="appmenu-item" href="/"' in html, "Projects must not be current on Settings"


def test_a_page_in_no_section_marks_nothing():
    assert _marked(_nav_items("")) == 0


# ─── the breadcrumb ────────────────────────────────────────────────────

def test_a_top_level_section_has_no_parent():
    # Stats and Settings are siblings of Projects, not children of it.
    for label in ("Stats", "Settings"):
        crumb = _breadcrumb((label, None))
        assert "Projects" not in crumb, f"{label} must not claim to live under Projects: {crumb}"
        assert f'<span class="here">{label}</span>' in crumb


def test_a_chat_shows_its_full_path():
    project_label, chat_title = "atk", "Session"
    crumb = _breadcrumb(("Projects", "/"), (project_label, "/-hash/"), (chat_title, None))
    assert '<a href="/">Projects</a>' in crumb
    assert '<a href="/-hash/">atk</a>' in crumb
    assert f'<span class="here">{chat_title}</span>' in crumb


def test_only_the_last_crumb_is_plain_text():
    crumb = _breadcrumb(("Projects", "/"), ("atk", None))
    assert crumb.count('class="here"') == 1


def test_breadcrumb_escapes_a_label_that_looks_like_markup():
    crumb = _breadcrumb(("<script>alert(1)</script>", None))
    assert "<script>" not in crumb
    assert "&lt;script&gt;" in crumb


if __name__ == "__main__":
    run_module_tests(globals())
