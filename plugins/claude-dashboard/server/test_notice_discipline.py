"""Repo-wide gates that keep error copy and notice markup in one place.
Run: ../.venv/bin/python test_notice_discipline.py
"""

import re
from pathlib import Path

from notices import catalog
from testutil import run_module_tests

SERVER = Path(__file__).resolve().parent
PLUGIN = SERVER.parent

# The only files allowed to spell notice markup tokens: the renderer, the
# client, the stylesheet, and the ingest fence that rejects forgeries.
MARKUP_OWNERS = {"notices_html.py", "notices.js", "dashboard.css", "agent_io.py"}
MARKUP_TOKENS = ("notice__", "notice--", "notices__", "data-notice-")

# Copy the consolidation deleted; reappearing anywhere means a regression.
BANNED_LITERALS = (
    "AUTH_HEALTH",
    "auth-banner",
    'class="err"',
    "Server unreachable",
    "check runtime/server.log",
    "regen errors",
    "can’t authenticate",
)


def _sources():
    for pattern in ("server/*.py", "assets/*.js", "templates/*.html"):
        for path in sorted(PLUGIN.glob(pattern)):
            if path.name.startswith("test_"):
                continue
            yield path, path.read_text(encoding="utf-8")


def test_deleted_error_idioms_never_come_back():
    for path, text in _sources():
        for literal in BANNED_LITERALS:
            assert literal not in text, f"{path.name} reintroduces {literal!r}"


def test_notice_markup_is_spelled_in_one_place():
    for path, text in _sources():
        if path.name in MARKUP_OWNERS:
            continue
        for token in MARKUP_TOKENS:
            assert token not in text, f"{path.name} hand-writes {token!r} markup"


def test_every_referenced_notice_code_exists_in_the_catalog():
    code_re = re.compile(
        r'"((?:account|rebuild|chat|net|page|settings|store|notice)\.[a-z_]+)"')
    known = set(catalog())
    for path, text in _sources():
        if path.name == "notices.py":
            continue
        for code in code_re.findall(text):
            if code.rsplit(".", 1)[1] in ("json", "html", "js", "css"):
                continue
            assert code in known, f"{path.name} references unknown code {code!r}"


if __name__ == "__main__":
    run_module_tests(globals())
