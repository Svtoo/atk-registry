"""Tests for the notice catalog (notices.py): the copy policy every entry must
satisfy, and the classifier that turns a raw failure into a code.
Run: ../.venv/bin/python test_notices.py
"""

import json
import re

import notices
from notices import (CLIENT_CODES, Notice, Step, catalog, classify, envelope,
                     from_probe, is_permanent, label)
from testutil import run_module_tests

SEVERITIES = {"blocked", "degraded", "bug", "info"}
SCOPES = {"app", "page", "chat", "field"}
DISMISSALS = {"none", "ack", "auto"}

# Raw text the CLI and the plugin actually produce, quoted from the failures
# they come from.
AUTH_MESSAGE = (
    "claude -p exited 1 after 3.0s\n--- stderr ---\n(empty)\n--- stdout ---\n"
    "Failed to authenticate. API Error: 401 OAuth access token has expired. "
    "Re-authenticate to continue."
)
CREDIT_MESSAGE = "Credit balance is too low"
USAGE_LIMIT_MESSAGE = "Claude usage limit reached. Your limit will reset at 3pm."
CLI_MISSING_MESSAGE = "claude CLI not found on PATH"
ERRNO_MESSAGE = "[Errno 2] No such file or directory: 'claude'"
TOO_LONG_MESSAGE = "claude -p exited 1 after 1.1s\n--- stdout ---\nPrompt is too long"
MODEL_DENIED_MESSAGE = "API Error: 403 Your account does not have access to this model"
JUNK_MESSAGE = "socket connection closed unexpectedly"

# Words a person cannot act on: our internals, protocol names, and the one word
# the whole consolidation exists to remove. Shell commands are exempt because
# they are literals the person copies, not prose they must understand.
JARGON = (
    r"\bauth\b", r"\b401\b", r"\b403\b", r"\bHTTP\b", r"\bJSON\b", r"\bstderr\b",
    r"\bstdout\b", r"\bsubprocess\b", r"\btraceback\b", r"\bexit code\b",
    r"\bPATH\b", r"\buuid\b", r"\bsqlite\b", r"\bendpoint\b", r"\bregen\b",
    r"\bsidecar\b", r"\bpayload\b", r"\binitialised\b", r"\bContent-Type\b",
    r"\bstate\.json\b", r"\bserver\.log\b",
)

RECOVERY_PROMISES = ("on its own", "on their own", "automatically", "will try again")

# The one field that passes server prose straight through: config._coerce
# already writes user-facing sentences.
PASSTHROUGH_TITLES = {"settings.rejected"}


def _prose(n: Notice) -> list:
    """Every string the person reads, excluding shell commands."""
    parts = [n.title, n.what, n.label, n.explain]
    parts.extend(s.text for s in n.steps)
    parts.extend(s.href_label for s in n.steps)
    return [p for p in parts if p]


# ─── the catalog is well formed ────────────────────────────────────────

def test_every_entry_declares_a_known_severity_scope_and_dismissal():
    for code, n in catalog().items():
        assert n.severity in SEVERITIES, (code, n.severity)
        assert n.scope in SCOPES, (code, n.scope)
        assert n.dismiss in DISMISSALS, (code, n.dismiss)


def test_every_entry_is_keyed_by_its_own_code():
    for code, n in catalog().items():
        assert n.code == code, (code, n.code)


def test_every_code_is_a_dotted_area_and_condition():
    pattern = re.compile(r"^[a-z]+\.[a-z_]+$")
    for code in catalog():
        assert pattern.match(code), code


def test_every_client_code_exists_in_the_catalog():
    # Notices.local clones a pre-rendered template by code; a missing entry
    # would render nothing exactly when the network is already gone.
    for code in CLIENT_CODES:
        assert code in catalog(), code


# ─── the copy policy ───────────────────────────────────────────────────

def test_a_person_who_is_stuck_is_always_told_what_to_do():
    # No exemption field exists on purpose: an escape hatch would let an
    # instruction-free banner be reintroduced legally.
    for code, n in catalog().items():
        if n.severity not in ("blocked", "bug"):
            continue
        assert n.steps, f"{code} leaves the person stuck with no step"
        actionable = any(s.command or s.href for s in n.steps) or n.report
        assert actionable, f"{code} has steps but nothing the person can act on"


def test_no_entry_uses_a_word_the_person_cannot_act_on():
    for code, n in catalog().items():
        prose = " ".join(_prose(n))
        if code in PASSTHROUGH_TITLES:
            prose = prose.replace(n.title, "")
        for pattern in JARGON:
            assert not re.search(pattern, prose, re.IGNORECASE), (code, pattern)


def test_two_problems_never_share_a_headline():
    # This is what forces signed-out, out-of-limit, out-of-credit and
    # not-installed to read as four different problems.
    titles = [n.title for c, n in catalog().items() if c not in PASSTHROUGH_TITLES]
    assert len(titles) == len(set(titles)), "duplicate title"


def test_two_problems_never_share_a_short_label():
    labels = [n.label for n in catalog().values()]
    assert len(labels) == len(set(labels)), "duplicate label"


def test_a_notice_never_promises_a_recovery_it_does_not_have():
    for code, n in catalog().items():
        if n.self_heals:
            continue
        text = (n.title + " " + n.what).lower()
        for promise in RECOVERY_PROMISES:
            assert promise not in text, (code, promise)


def test_a_title_is_one_readable_sentence():
    max_title_chars = 120
    for code, n in catalog().items():
        if code in PASSTHROUGH_TITLES:
            continue
        assert n.title.endswith("."), (code, n.title)
        assert len(n.title) <= max_title_chars, (code, len(n.title))
        assert "\n" not in n.title, code


def test_a_real_problem_explains_itself_beyond_its_title():
    min_what_chars = 80
    for code, n in catalog().items():
        if n.severity == "info":
            continue
        assert len(n.what) >= min_what_chars, (code, len(n.what))


def test_a_short_label_stays_short():
    max_label_words = 4
    for code, n in catalog().items():
        assert n.label, code
        assert len(n.label.split()) <= max_label_words, (code, n.label)


def test_a_step_never_points_at_something_elsewhere_on_the_page():
    # The defect this replaces: a pending lead that points at a banner which is
    # hidden once the entry is acknowledged.
    for code, n in catalog().items():
        for step in n.steps:
            lowered = step.text.lower()
            for pointer in ("above", "below", "the note"):
                assert pointer not in lowered, (code, step.text)


def test_the_sign_in_notice_explains_where_summaries_come_from():
    signed_out = catalog()["account.signed_out"]
    assert "Claude Code" in signed_out.what
    assert "subscription" in signed_out.what
    assert signed_out.explain, "the long-form answer to 'why does this need a sign in'"


def test_the_sign_in_notice_hands_over_the_exact_command():
    signed_out = catalog()["account.signed_out"]
    commands = [s.command for s in signed_out.steps if s.command]
    assert "claude auth login" in commands, commands


def test_diagnostics_never_carry_the_project_path():
    # The project hash is a slug of the filesystem path: it would put the
    # person's username and directory layout into a public issue.
    secret_hash = "-Users-someone-secret-project"
    env = envelope("rebuild.too_large",
                   measurements={"model": "sonnet", "project_hash": secret_hash})
    blob = repr(env["diagnostics"])
    assert secret_hash not in blob and "project_hash" not in blob, blob


def test_copied_diagnostics_never_include_the_raw_failure_text():
    raw = "claude -p exited 1\nOAuth token expired"
    env = envelope("rebuild.too_large", detail=raw,
                   measurements={"model": "sonnet"})
    copied = next(a["value"] for a in env["actions"]
                  if a["label"] == "Copy diagnostics")
    assert "exited 1" not in copied and "OAuth" not in copied, copied


# ─── classification ────────────────────────────────────────────────────

def test_an_expired_sign_in_is_recognised():
    assert classify("SubprocessFailed", AUTH_MESSAGE) == "account.signed_out"


def test_a_usage_limit_is_not_reported_as_a_sign_in_problem():
    assert classify("SubprocessFailed", USAGE_LIMIT_MESSAGE) == "account.usage_limit"


def test_an_empty_balance_is_not_reported_as_a_sign_in_problem():
    code = classify("SubprocessFailed", CREDIT_MESSAGE)
    assert code == "account.no_credit"
    assert catalog()[code].severity == "blocked"


def test_an_empty_balance_does_not_blame_anyone():
    # The message cannot tell a credit-billed account apart from a
    # misconfigured one, so it states the fact and offers both branches.
    n = catalog()["account.no_credit"]
    assert not n.report, "this is not a bug report"
    assert "our side" not in n.title and "fault" not in n.what
    commands = [s.command for s in n.steps if s.command]
    assert "claude auth status" in commands, "which account is signed in"
    assert "claude auth login" in commands, "switching to the intended account"


def test_an_empty_balance_is_checked_before_the_usage_limit_and_the_sign_in():
    # A message could plausibly carry more than one marker; the order decides
    # which headline the person reads.
    both = f"{CREDIT_MESSAGE}. {USAGE_LIMIT_MESSAGE} 401 re-authenticate"
    assert classify("SubprocessFailed", both) == "account.no_credit"


def test_a_usage_limit_is_checked_before_the_sign_in():
    both = f"{USAGE_LIMIT_MESSAGE} 401 re-authenticate"
    assert classify("SubprocessFailed", both) == "account.usage_limit"


def test_a_missing_cli_is_recognised_from_either_wording():
    assert classify("", CLI_MISSING_MESSAGE) == "account.cli_missing"
    assert classify("", ERRNO_MESSAGE) == "account.cli_missing"


def test_a_denied_model_is_not_reported_as_a_sign_in_problem():
    # This message carries a 403, so it reads as a sign-in problem unless the
    # model marker is checked first.
    assert "403" in MODEL_DENIED_MESSAGE
    assert classify("SubprocessFailed", MODEL_DENIED_MESSAGE) == "account.model_denied"


def test_an_oversized_prompt_is_recognised():
    assert classify("SubprocessFailed", TOO_LONG_MESSAGE) == "rebuild.too_large"


def test_the_failure_class_wins_over_the_message_text():
    # A timeout carries the whole transcript tail, which may contain anything.
    assert classify("RegenTimeout", AUTH_MESSAGE) == "rebuild.timeout"


def test_a_retired_failure_class_still_classifies():
    # FragmentRejected is gone from the source but survives in sidecars on disk.
    assert classify("FragmentRejected", "empty output") == "rebuild.bad_output"


def test_an_unrecognised_failure_falls_back_to_the_plain_one():
    assert classify("SubprocessFailed", JUNK_MESSAGE) == "rebuild.failed"


def test_an_unrecognised_probe_result_is_an_unknown_not_a_failure():
    assert classify("AuthProbe", JUNK_MESSAGE) == "account.check_unclear"


def test_missing_kind_and_message_do_not_raise():
    assert classify("", "") == "rebuild.failed"


def test_the_fallback_notice_does_not_lead_with_a_bug_report():
    # The defect this replaces: a signed-out person being told to file a bug.
    fallback = catalog()[classify("SubprocessFailed", JUNK_MESSAGE)]
    assert fallback.severity != "bug"
    assert "report" not in fallback.title.lower()


# ─── retrying, or not ──────────────────────────────────────────────────

def test_a_problem_only_the_person_can_fix_is_not_retried():
    for code in ("account.signed_out", "account.usage_limit", "account.cli_missing",
                 "account.model_denied", "account.no_credit", "rebuild.too_large"):
        assert is_permanent(code), code


def test_a_transient_problem_is_retried():
    for code in ("rebuild.timeout", "rebuild.bad_output", "rebuild.failed"):
        assert not is_permanent(code), code


# ─── the probe ─────────────────────────────────────────────────────────

def test_a_healthy_probe_raises_nothing():
    assert from_probe(True, "", "ok") is None


def test_a_probe_that_cannot_find_the_cli_says_so_exactly():
    assert from_probe(False, "CliMissing", CLI_MISSING_MESSAGE) == "account.cli_missing"


def test_a_probe_that_timed_out_admits_it_does_not_know():
    timeout_detail = "probe timed out after 25s"
    assert from_probe(False, "ProbeTimeout", timeout_detail) == "account.check_unclear"


def test_a_probe_that_hit_a_credit_balance_reports_our_bug():
    assert from_probe(False, "SubprocessFailed", CREDIT_MESSAGE) == "account.no_credit"


# ─── the short label ───────────────────────────────────────────────────

def test_the_label_of_a_known_code_is_its_catalog_label():
    timeout_code = "rebuild.timeout"
    assert label(timeout_code) == catalog()[timeout_code].label


def test_the_label_of_an_unknown_code_falls_back_to_the_plain_one():
    fallback_label = catalog()["rebuild.failed"].label
    assert label("nothing.likethis") == fallback_label


# ─── the envelope handed to the renderer and the wire ──────────────────

def test_an_envelope_carries_the_copy_and_the_raw_text_apart():
    detail_text = "claude -p exited 1"
    env = envelope("account.signed_out", detail=detail_text)
    assert env["code"] == "account.signed_out"
    assert env["title"] == catalog()["account.signed_out"].title
    assert env["detail"] == detail_text
    assert detail_text not in env["title"] and detail_text not in env["what"]


def test_an_envelope_fills_only_the_facts_the_entry_declares():
    # Facts live in `what`, never in a title: a title that loses its only
    # sentence to a missing fact would render empty.
    limit_seconds = 240
    typical_seconds = 95
    env = envelope("rebuild.timeout",
                   facts={"limit_s": limit_seconds, "typical_s": typical_seconds})
    assert str(limit_seconds) in env["what"], env["what"]
    assert str(typical_seconds) in env["what"], env["what"]


def test_no_title_depends_on_a_fact_that_might_be_missing():
    for code, n in catalog().items():
        if code in PASSTHROUGH_TITLES:
            continue
        assert "{" not in n.title, (code, n.title)


def test_an_envelope_rounds_a_measured_number_to_something_readable():
    # Wall times arrive as floats from the store, and nobody reads milliseconds
    # of a four-minute limit.
    measured_limit = 240.0
    measured_typical = 82.083
    env = envelope("rebuild.timeout",
                   facts={"limit_s": measured_limit, "typical_s": measured_typical})
    assert "240 seconds" in env["what"], env["what"]
    assert "82 seconds" in env["what"], env["what"]
    assert "240.0" not in env["what"] and "82.083" not in env["what"]


def test_an_envelope_leaves_a_whole_number_alone():
    exact_limit = 180
    env = envelope("rebuild.timeout", facts={"limit_s": exact_limit})
    assert f"{exact_limit} seconds" in env["what"], env["what"]


def test_an_envelope_leaves_no_empty_placeholder_when_a_fact_is_missing():
    env = envelope("rebuild.timeout", facts={"limit_s": 180})
    assert "{" not in env["title"] and "}" not in env["title"]
    assert "{" not in env["what"] and "}" not in env["what"]
    assert "None" not in env["what"], env["what"]


def test_an_envelope_never_interpolates_text_it_was_not_asked_for():
    # A fact value that itself looks like a placeholder must not be expanded.
    hostile_fact = "{limit_s}"
    env = envelope("settings.rejected", facts={"reason": hostile_fact})
    assert env["title"] == hostile_fact


def test_an_envelope_uses_camel_case_for_the_browser():
    env = envelope("account.signed_out")
    assert "selfHeals" in env and "self_heals" not in env
    for step in env["steps"]:
        assert "hrefLabel" in step and "href_label" not in step


def test_a_reportable_notice_offers_the_prefilled_issue_and_the_diagnostics():
    env = envelope("rebuild.too_large", measurements={"model": "sonnet"})
    labels = {a["label"] for a in env["actions"]}
    assert "Report it on GitHub" in labels
    assert "Copy diagnostics" in labels


def test_a_notice_the_person_can_fix_does_not_offer_a_report():
    env = envelope("account.signed_out")
    labels = {a["label"] for a in env["actions"]}
    assert "Report it on GitHub" not in labels


def test_an_envelope_keeps_the_persisted_identity_of_a_stored_failure():
    stored_id = "e7f3a1b2"
    stored_at = 1784750000
    env = envelope("rebuild.timeout", id=stored_id, at=stored_at, acked_at=None,
                   project="-Users-someone-proj", session="abc-123")
    assert env["id"] == stored_id
    assert env["at"] == stored_at
    assert env["ackedAt"] is None
    assert env["session"] == "abc-123"


def test_an_unknown_code_still_produces_a_usable_envelope():
    env = envelope("nothing.likethis")
    assert env["title"] and env["what"] and env["severity"] in SEVERITIES


# ─── the live-editable wording overlay ─────────────────────────────────

def _overlay(tmp_text: str, fn):
    """Point the catalog at an overlay file for one call, then restore."""
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "notices.json"
        path.write_text(tmp_text, encoding="utf-8")
        original = notices.OVERLAY_PATH
        notices.OVERLAY_PATH = path
        notices._CACHE.clear()
        try:
            return fn()
        finally:
            notices.OVERLAY_PATH = original
            notices._CACHE.clear()


def test_a_missing_overlay_leaves_the_built_in_wording_alone():
    from pathlib import Path
    original = notices.OVERLAY_PATH
    notices.OVERLAY_PATH = Path("/nonexistent/notices.json")
    notices._CACHE.clear()
    try:
        assert catalog()["account.signed_out"].title
    finally:
        notices.OVERLAY_PATH = original
        notices._CACHE.clear()


def test_an_overlay_can_reword_a_notice():
    reworded = "You are signed out."
    overlay = json.dumps({"account.signed_out": {"title": reworded}})
    result = _overlay(overlay, lambda: catalog()["account.signed_out"].title)
    assert result == reworded


def test_a_broken_overlay_never_takes_the_dashboard_down():
    # read_template fails open and there is no 5xx path, so a stray comma in a
    # live-edited file must not raise out of catalog().
    broken = '{"account.signed_out": {"title": "x",}}'
    result = _overlay(broken, lambda: catalog()["account.signed_out"])
    assert result.title, "built-in wording must survive a malformed overlay"


def test_a_broken_overlay_says_so_on_the_page():
    broken = '{"account.signed_out": {"title": "x",}}'
    codes = _overlay(broken, lambda: list(notices.overlay_problems()))
    assert codes == ["notice.copy_unreadable"], codes


def test_an_overlay_cannot_change_how_serious_a_notice_is():
    overlay = json.dumps({"account.signed_out": {"severity": "info"}})
    result = _overlay(overlay, lambda: catalog()["account.signed_out"].severity)
    assert result == "blocked", "severity is policy, not wording"


def test_an_overlay_cannot_change_a_command_the_person_will_run():
    overlay = json.dumps(
        {"account.signed_out": {"steps": [{"command": "rm -rf /"}]}})
    result = _overlay(overlay, lambda: catalog()["account.signed_out"])
    commands = [s.command for s in result.steps if s.command]
    assert "rm -rf /" not in commands, "commands are code, not wording"


def test_an_overlay_for_a_code_that_does_not_exist_is_ignored():
    overlay = json.dumps({"nothing.likethis": {"title": "x"}})
    result = _overlay(overlay, lambda: "nothing.likethis" in catalog())
    assert result is False


def test_an_overlay_still_has_to_obey_the_copy_policy_at_runtime():
    # Rewording must not be able to strip the instruction out of a blocked
    # notice, so the mandatory-remediation rule holds against a live edit too.
    overlay = json.dumps({"account.signed_out": {"steps": []}})
    result = _overlay(overlay, lambda: catalog()["account.signed_out"])
    assert result.steps, "an overlay cannot remove the steps"


if __name__ == "__main__":
    run_module_tests(globals())
