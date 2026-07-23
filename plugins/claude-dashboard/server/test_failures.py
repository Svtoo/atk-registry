"""Tests for failure presentation (failures.py): the right rule matches, the
copy carries live numbers, and nothing raw reaches the person except in detail.
Run: ../.venv/bin/python test_failures.py
"""

from urllib.parse import parse_qs, urlparse

from failures import REPORT_URL, present
from testutil import run_module_tests

AUTH_MESSAGE = (
    "claude -p exited 1 after 3.0s\n--- stderr ---\n(empty)\n--- stdout ---\n"
    "Failed to authenticate. API Error: 401 OAuth access token has expired. "
    "Re-authenticate to continue."
)
TOO_LONG_MESSAGE = "claude -p exited 1 after 1.1s\n--- stdout ---\nPrompt is too long"
TIMEOUT_MESSAGE = "claude -p exceeded 180s wall-clock and was killed (ran 180.0s); produced nothing"


def _actions(p):
    return {a["label"]: a for a in p["actions"]}


# ─── sign in ───────────────────────────────────────────────────────────

def test_an_expired_sign_in_asks_the_person_to_act():
    p = present("SubprocessFailed", AUTH_MESSAGE)
    assert p["kind"] == "auth_expired"
    assert p["severity"] == "action", "only this one needs the person to do something"
    assert "sign in" in p["title"].lower()


def test_the_sign_in_action_is_the_exact_cli_command():
    p = present("SubprocessFailed", AUTH_MESSAGE)
    action = list(_actions(p).values())[0]
    assert action["kind"] == "command"
    assert action["value"] == "claude auth login", action


def test_the_other_401_wording_matches_the_same_rule():
    other = "Failed to authenticate. API Error: 401 Invalid authentication credentials"
    assert present("SubprocessFailed", other)["kind"] == "auth_expired"


# ─── too big ───────────────────────────────────────────────────────────

def test_an_oversized_update_is_owned_as_our_bug():
    p = present("SubprocessFailed", TOO_LONG_MESSAGE)
    assert p["kind"] == "prompt_too_long"
    assert p["severity"] == "bug"
    assert "our side" in p["title"], "the wording must not blame the person"


def test_reporting_offers_both_a_link_and_a_copyable_link():
    # The dashboard often runs in a browser pane that is not signed in to
    # GitHub, so the link on its own is a dead end.
    actions = _actions(present("SubprocessFailed", TOO_LONG_MESSAGE))
    assert actions["Report it on GitHub"]["kind"] == "link"
    assert actions["Copy link"]["kind"] == "copy"
    assert actions["Copy link"]["value"] == actions["Report it on GitHub"]["value"], \
        "the copied link must be the one the button opens"


def test_the_report_link_opens_a_prefilled_new_issue_in_the_registry():
    url = _actions(present("SubprocessFailed", TOO_LONG_MESSAGE))["Report it on GitHub"]["value"]
    assert url.startswith(REPORT_URL + "/new?"), url
    parsed = parse_qs(urlparse(url).query)
    assert "claude-dashboard" in parsed["title"][0]
    assert parsed["labels"][0] == "bug,plugin: claude-dashboard", parsed["labels"]


def test_the_report_body_asks_for_diagnostics_rather_than_dumping_them():
    url = _actions(present("SubprocessFailed", TOO_LONG_MESSAGE))["Report it on GitHub"]["value"]
    body = parse_qs(urlparse(url).query)["body"][0]
    assert "Copy diagnostics" in body, "the body must point at the copy button"
    assert "Describe what the chat was doing" in body, "it must ask the person what happened"
    assert "exited 1" not in body, "raw output is not auto-pasted into a public issue"


# ─── timed out ─────────────────────────────────────────────────────────

def test_a_timeout_names_the_configured_limit_not_a_hardcoded_one():
    configured_limit = 240
    p = present("RegenTimeout", TIMEOUT_MESSAGE, timeout_s=configured_limit)
    assert p["kind"] == "regen_timeout"
    assert "240 seconds" in p["title"], p["title"]


def test_a_timeout_mentions_this_chats_usual_time_when_known():
    p = present("RegenTimeout", TIMEOUT_MESSAGE, timeout_s=180, typical_s=95)
    assert "95 seconds" in p["body"], p["body"]


def test_a_timeout_without_a_known_usual_time_still_reads_well():
    p = present("RegenTimeout", TIMEOUT_MESSAGE, timeout_s=180)
    assert "try again" in p["body"]
    assert "None" not in p["body"] and "None" not in p["title"]


def test_a_timeout_points_at_the_setting_that_controls_it():
    p = present("RegenTimeout", TIMEOUT_MESSAGE, timeout_s=180)
    assert _actions(p)["Settings"]["value"] == "/settings"


# ─── anything else ─────────────────────────────────────────────────────

def test_an_unrecognised_failure_still_gets_a_plain_message():
    p = present("SubprocessFailed", "socket connection closed unexpectedly")
    assert p["kind"] == "unknown"
    assert p["title"] and p["body"]
    assert _actions(p)["Report it on GitHub"]["value"].startswith(REPORT_URL + "/new?")


def test_the_raw_text_is_kept_only_as_detail():
    p = present("SubprocessFailed", AUTH_MESSAGE)
    assert p["detail"] == AUTH_MESSAGE, "raw text stays available for diagnostics"
    assert "exited 1" not in p["title"] and "exited 1" not in p["body"], \
        "raw CLI text must never be the message a person reads"


def test_missing_kind_and_message_do_not_raise():
    p = present("", "")
    assert p["severity"] and p["title"]


# ─── diagnostics: useful numbers, nothing from the conversation ────────

MEASUREMENTS = {
    "ts": 1784750000, "model": "sonnet", "kind": "SubprocessFailed",
    "prompt_words": 80133, "input_tokens": 27288, "output_tokens": 0,
    "output_bytes": 0, "wall_ms": 1100, "attempts": 1,
}


def _diag(p):
    return {d["label"]: d["value"] for d in p["diagnostics"]}


def test_diagnostics_carry_the_numbers_that_explain_the_failure():
    configured_limit = 180
    p = present("SubprocessFailed", TOO_LONG_MESSAGE,
                timeout_s=configured_limit, measurements=MEASUREMENTS)
    d = _diag(p)
    assert d["Plugin"] == "claude-dashboard"
    assert d["Prompt size (words)"] == MEASUREMENTS["prompt_words"], \
        "the size is the whole point for this failure"
    assert d["Model"] == MEASUREMENTS["model"]
    assert d["Time limit (s)"] == configured_limit
    assert "When (UTC)" in d


def test_diagnostics_never_carry_the_project_path_or_the_raw_output():
    # The project hash is a slug of the filesystem path, so it would put the
    # person's username and directory layout into a public issue.
    p = present("SubprocessFailed", AUTH_MESSAGE, timeout_s=180,
                measurements={**MEASUREMENTS, "project_hash": "-Users-someone-secret-project"})
    blob = repr(p["diagnostics"])
    assert "project_hash" not in blob and "-Users-" not in blob, blob
    assert "OAuth" not in blob, "the raw failure text must not leak into diagnostics"


def test_diagnostics_survive_having_no_measurements():
    d = _diag(present("SubprocessFailed", TOO_LONG_MESSAGE))
    assert d["Plugin"] == "claude-dashboard"
    assert d["Failure"] == "prompt_too_long"


def test_a_reportable_failure_offers_to_copy_the_diagnostics():
    actions = _actions(present("SubprocessFailed", TOO_LONG_MESSAGE,
                               timeout_s=180, measurements=MEASUREMENTS))
    copied = actions["Copy diagnostics"]["value"]
    assert copied.startswith("Plugin: claude-dashboard")
    assert f"Prompt size (words): {MEASUREMENTS['prompt_words']}" in copied
    assert "exited 1" not in copied, "copying must not include the raw output"


def test_a_failure_the_person_can_fix_does_not_offer_a_report():
    # An expired sign in is not a bug, so it gets no report or copy action.
    labels = _actions(present("SubprocessFailed", AUTH_MESSAGE)).keys()
    assert "Report it on GitHub" not in labels
    assert "Copy diagnostics" not in labels


if __name__ == "__main__":
    run_module_tests(globals())
