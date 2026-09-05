#!/usr/bin/env python3
"""Tests for the mental-models command: creation guardrails, trigger updates,
cost surfacing, rebuild and audit."""
import datetime
import json
import unittest
from unittest import mock

import fakes
from hindsight_cli import client, shell

MM_URL = "http://localhost:8888/v1/default/banks/default/mental-models"
MODEL_ID = "writing-code"
QUERY = "How does this user want code written?"
CRON = "0 17 * * 1,4"
FULL_TRIGGER = {"mode": "delta", "fact_types": ["observation"],
                "exclude_mental_models": True, "refresh_cron": CRON}


class CreateTest(unittest.TestCase):
    def setUp(self):
        self.http = fakes.FakeHttp([("POST %s" % MM_URL, "{}")])
        patcher = mock.patch.object(client, "http", self.http)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_create_defaults_the_budget_to_800_tokens(self):
        # When a model is created without --max-tokens
        code, out, _ = fakes.invoke(
            ["mental-models", "create", MODEL_ID,
             "--query", QUERY, "--cron", CRON])
        # Then the create request carries the 800 token default
        self.assertEqual(code, 0)
        self.assertEqual(out, "  created %s\n" % MODEL_ID)
        self.assertEqual(len(self.http.requests), 1)
        method, url, body = self.http.requests[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, MM_URL)
        self.assertEqual(body, {
            "id": MODEL_ID, "name": MODEL_ID, "source_query": QUERY,
            "trigger": {"mode": "delta", "fact_types": ["observation"],
                        "exclude_mental_models": True, "refresh_cron": CRON},
            "max_tokens": 800})
        self.http.assert_done()

    def test_create_without_cron_warns_no_schedule(self):
        # When a model is created without --cron
        code, out, err = fakes.invoke(
            ["mental-models", "create", MODEL_ID, "--query", QUERY])
        # Then the command succeeds and the schedule warning goes to stderr
        self.assertEqual(code, 0)
        self.assertEqual(out, "  created %s\n" % MODEL_ID)
        self.assertEqual(
            err, "  ⚠ no schedule set. Add one with: --cron '0 17 * * 1,4'\n")

    def test_create_warns_when_the_budget_exceeds_1000_tokens(self):
        budget = 1500
        # When a model is created with a budget past 1000 tokens
        code, out, err = fakes.invoke(
            ["mental-models", "create", MODEL_ID, "--query", QUERY,
             "--cron", CRON, "--max-tokens", str(budget)])
        # Then the model is still created and the budget band is flagged
        self.assertEqual(code, 0)
        self.assertEqual(out, "  created %s\n" % MODEL_ID)
        self.assertEqual(
            err, "  ⚠ max-tokens %d: models hold their budget best"
                 " at 600-800\n" % budget)
        self.assertEqual(len(self.http.requests), 1)
        self.assertEqual(self.http.requests[0][2]["max_tokens"], budget)

    def test_create_warns_when_the_query_exceeds_two_sentences(self):
        query = ("How does the user test? What frameworks appear? "
                 "Also list the flaky suites.")
        # When a model is created with a three sentence query
        code, out, err = fakes.invoke(
            ["mental-models", "create", MODEL_ID, "--query", query,
             "--cron", CRON])
        # Then the model is still created and the query shape is flagged
        self.assertEqual(code, 0)
        self.assertEqual(out, "  created %s\n" % MODEL_ID)
        self.assertEqual(
            err, "  ⚠ query has 3 sentences: multi-facet questions produce"
                 " multi-section documents that overrun their budget\n")


class SetTest(unittest.TestCase):
    def setUp(self):
        self.http = fakes.FakeHttp([
            ("GET %s/%s?detail=full" % (MM_URL, MODEL_ID),
             json.dumps({"id": MODEL_ID, "trigger": FULL_TRIGGER})),
            ("PATCH %s/%s" % (MM_URL, MODEL_ID), "{}")])
        patcher = mock.patch.object(client, "http", self.http)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_set_cron_preserves_the_rest_of_the_trigger(self):
        updated_cron = "30 6 * * 2"
        # When only the cron is set
        code, out, _ = fakes.invoke(
            ["mental-models", "set", MODEL_ID, "--cron", updated_cron])
        # Then the patched trigger keeps every other field
        self.assertEqual(code, 0)
        self.assertEqual(out, "  updated %s\n" % MODEL_ID)
        self.assertEqual(len(self.http.requests), 2)
        method, _, body = self.http.requests[1]
        self.assertEqual(method, "PATCH")
        self.assertEqual(
            body, {"trigger": {**FULL_TRIGGER, "refresh_cron": updated_cron}})
        self.http.assert_done()

    def test_set_mode_updates_only_the_mode_in_the_trigger(self):
        updated_mode = "full"
        # When only the mode is set
        code, out, _ = fakes.invoke(
            ["mental-models", "set", MODEL_ID, "--mode", updated_mode])
        # Then the patched trigger keeps every other field
        self.assertEqual(code, 0)
        self.assertEqual(out, "  updated %s\n" % MODEL_ID)
        self.assertEqual(len(self.http.requests), 2)
        method, _, body = self.http.requests[1]
        self.assertEqual(method, "PATCH")
        self.assertEqual(
            body, {"trigger": {**FULL_TRIGGER, "mode": updated_mode}})
        self.http.assert_done()

    def test_set_rejects_unknown_modes(self):
        # When the mode is neither delta nor full
        code, out, err = fakes.invoke(
            ["mental-models", "set", MODEL_ID, "--mode", "weekly"])
        # Then the command dies before talking to the API
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertEqual(err, "  ❌ --mode must be delta or full\n")
        self.assertEqual(len(self.http.requests), 0)

    def test_set_query_flags_the_full_rebuild(self):
        updated_query = "How does this user structure tests?"
        # When the query is set
        code, out, _ = fakes.invoke(
            ["mental-models", "set", MODEL_ID, "--query", updated_query])
        # Then the update names the rebuild consequence
        self.assertEqual(code, 0)
        self.assertEqual(out, ("  updated %s\n"
                               "  query changed: the next refresh is a full"
                               " rebuild; refresh now on approval, do not"
                               " leave it for the cron\n") % MODEL_ID)
        self.assertEqual(len(self.http.requests), 2)
        method, _, body = self.http.requests[1]
        self.assertEqual(method, "PATCH")
        self.assertEqual(body, {"source_query": updated_query})
        self.http.assert_done()

    def test_set_keep_trace_turns_the_trace_on_in_the_trigger(self):
        # When the trace is turned on
        code, out, _ = fakes.invoke(
            ["mental-models", "set", MODEL_ID, "--keep-trace"])
        # Then the patched trigger keeps every other field
        self.assertEqual(code, 0)
        self.assertEqual(out, "  updated %s\n" % MODEL_ID)
        self.assertEqual(len(self.http.requests), 2)
        method, _, body = self.http.requests[1]
        self.assertEqual(method, "PATCH")
        self.assertEqual(
            body, {"trigger": {**FULL_TRIGGER, "keep_trace": True}})
        self.http.assert_done()

    def test_set_no_keep_trace_turns_the_trace_off_in_the_trigger(self):
        # When the trace is turned off
        code, out, _ = fakes.invoke(
            ["mental-models", "set", MODEL_ID, "--no-keep-trace"])
        # Then the patched trigger keeps every other field
        self.assertEqual(code, 0)
        self.assertEqual(out, "  updated %s\n" % MODEL_ID)
        self.assertEqual(len(self.http.requests), 2)
        method, _, body = self.http.requests[1]
        self.assertEqual(method, "PATCH")
        self.assertEqual(
            body, {"trigger": {**FULL_TRIGGER, "keep_trace": False}})
        self.http.assert_done()


class DryRunTest(unittest.TestCase):
    DIFF = ("--- current\n+++ preview\n@@ -1 +1,2 @@\n rule one\n+rule two\n")

    def _serve(self, **overrides):
        report = {
            "effective_mode": "full",
            "mode_fallback_reason": None,
            "facts": {"retrieved": 63, "used": 62},
            "trace": {"tool_calls": [
                {"tool": "search_observations",
                 "input": {"query": "rules for claims"}, "result_count": 25},
                {"tool": "search_observations",
                 "input": {"query": "how output should read"},
                 "result_count": 38}]},
            "candidate_content": "x" * 4000,
            "diff": self.DIFF,
            "usage": {"input_tokens": 35543, "output_tokens": 699},
            "duration_ms": 77092,
            "warnings": []}
        report.update(overrides)
        self.http = fakes.FakeHttp([
            ("POST %s/%s/dry-run-refresh" % (MM_URL, MODEL_ID),
             json.dumps(report))])
        patcher = mock.patch.object(client, "http", self.http)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_dry_run_shows_the_diff_a_refresh_would_write(self):
        self._serve(mode_fallback_reason="source_query_changed",
                    warnings=["candidate exceeds max_tokens"])
        # When a dry run is requested
        code, out, _ = fakes.invoke(["mental-models", "dry-run", MODEL_ID])
        # Then one stat line, the warnings, then the unified diff verbatim
        self.assertEqual(code, 0)
        self.assertEqual(out, (
            "  mode full (source_query_changed)  searches 2"
            "  facts retrieved 63 used 62"
            "  candidate 4000 chars ~1000 tokens  77s\n"
            "  warning: candidate exceeds max_tokens\n"
            + self.DIFF))
        method, _, body = self.http.requests[0]
        self.assertEqual((method, body), ("POST", {}))
        self.http.assert_done()

    def test_dry_run_with_an_empty_diff_says_no_change(self):
        self._serve(diff="")
        # When the refresh would write identical content
        code, out, _ = fakes.invoke(["mental-models", "dry-run", MODEL_ID])
        # Then the report says so instead of printing nothing
        self.assertEqual(code, 0)
        self.assertEqual(out, (
            "  mode full  searches 2  facts retrieved 63 used 62"
            "  candidate 4000 chars ~1000 tokens  77s\n"
            "  no change\n"))
        self.http.assert_done()

    def test_dry_run_json_prints_the_raw_report(self):
        self._serve()
        # When the raw report is requested for tooling
        code, out, _ = fakes.invoke(
            ["mental-models", "dry-run", MODEL_ID, "--json"])
        # Then stdout is exactly the report as JSON
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["facts"], {"retrieved": 63, "used": 62})
        self.assertNotIn("searches", out)
        self.http.assert_done()


class RefreshTest(unittest.TestCase):
    def setUp(self):
        self.http = fakes.FakeHttp(
            [("POST %s/%s/refresh" % (MM_URL, MODEL_ID), "{}")])
        patcher = mock.patch.object(client, "http", self.http)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_refresh_states_the_cost_before_queueing(self):
        # When a refresh is requested
        code, out, _ = fakes.invoke(["mental-models", "refresh", MODEL_ID])
        # Then the cost line precedes the queued confirmation
        self.assertEqual(code, 0)
        self.assertEqual(out, ("  paid LLM run (cents); delta mode applies"
                               " only facts newer than the last refresh\n"
                               "  refresh queued for %s (runs in the"
                               " background)\n") % MODEL_ID)
        self.assertEqual(len(self.http.requests), 1)
        self.http.assert_done()


class RebuildTest(unittest.TestCase):
    def setUp(self):
        self.http = fakes.FakeHttp([
            ("POST %s/%s/clear" % (MM_URL, MODEL_ID), "{}"),
            ("POST %s/%s/refresh" % (MM_URL, MODEL_ID), "{}")])
        self.confirm = mock.Mock(return_value=True)
        for module, name, value in ((client, "http", self.http),
                                    (shell, "confirm", self.confirm)):
            patcher = mock.patch.object(module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_rebuild_declined_confirm_rebuilds_nothing(self):
        self.confirm.return_value = False
        # When the rebuild prompt is declined
        code, out, err = fakes.invoke(["mental-models", "rebuild", MODEL_ID])
        # Then nothing is cleared or refreshed
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertEqual(err, "  ❌ Aborted - nothing rebuilt.\n")
        self.assertEqual(len(self.http.requests), 0)
        self.confirm.assert_called_once_with(
            "Rebuild '%s' from scratch?" % MODEL_ID)

    def test_rebuild_yes_skips_the_prompt(self):
        # When --yes carries the user's consent from the conversation
        code, out, _ = fakes.invoke(
            ["mental-models", "rebuild", MODEL_ID, "--yes"])
        # Then no prompt is shown and the rebuild proceeds
        self.assertEqual(code, 0)
        self.assertEqual(out, "  refresh queued for %s (runs in the"
                              " background)\n" % MODEL_ID)
        self.confirm.assert_not_called()
        self.assertEqual(len(self.http.requests), 2)
        self.assertEqual(self.http.requests[0][:2],
                         ("POST", "%s/%s/clear" % (MM_URL, MODEL_ID)))
        self.assertEqual(self.http.requests[1][:2],
                         ("POST", "%s/%s/refresh" % (MM_URL, MODEL_ID)))
        self.http.assert_done()

    def test_rebuild_clears_then_refreshes(self):
        # When the rebuild prompt is confirmed
        code, out, _ = fakes.invoke(["mental-models", "rebuild", MODEL_ID])
        # Then the model is cleared, a refresh is queued and reported
        self.assertEqual(code, 0)
        self.assertEqual(out, "  refresh queued for %s (runs in the"
                              " background)\n" % MODEL_ID)
        self.assertEqual(len(self.http.requests), 2)
        self.assertEqual(self.http.requests[0][:2],
                         ("POST", "%s/%s/clear" % (MM_URL, MODEL_ID)))
        self.assertEqual(self.http.requests[1][:2],
                         ("POST", "%s/%s/refresh" % (MM_URL, MODEL_ID)))
        self.http.assert_done()


class DeleteYesTest(unittest.TestCase):
    def setUp(self):
        self.http = fakes.FakeHttp([("DELETE %s/%s" % (MM_URL, MODEL_ID), "")])
        self.confirm = mock.Mock()
        for module, name, value in ((client, "http", self.http),
                                    (shell, "confirm", self.confirm)):
            patcher = mock.patch.object(module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_delete_yes_skips_the_prompt(self):
        # When --yes carries the user's consent from the conversation
        code, out, _ = fakes.invoke(
            ["mental-models", "delete", MODEL_ID, "--yes"])
        # Then no prompt is shown and the model is deleted
        self.assertEqual(code, 0)
        self.assertEqual(out, "  deleted %s\n" % MODEL_ID)
        self.confirm.assert_not_called()
        self.assertEqual(len(self.http.requests), 1)
        self.assertEqual(self.http.requests[0][:2],
                         ("DELETE", "%s/%s" % (MM_URL, MODEL_ID)))
        self.http.assert_done()


class ReviewTest(unittest.TestCase):
    SIBLING_ID = "testing-style"
    SIBLING_QUERY = "What does this user expect of testing?"

    def setUp(self):
        items = {"items": [
            {"id": MODEL_ID, "max_tokens": 800, "source_query": QUERY,
             "content": "x" * 4000, "trigger": dict(FULL_TRIGGER),
             "last_refreshed_at": None, "last_memory_seen_at": None},
            {"id": self.SIBLING_ID, "max_tokens": 800,
             "source_query": self.SIBLING_QUERY, "content": "y" * 100,
             "trigger": dict(FULL_TRIGGER),
             "last_refreshed_at": None, "last_memory_seen_at": None},
        ]}
        self.http = fakes.FakeHttp(
            [("GET %s?detail=full" % MM_URL, json.dumps(items))])
        patcher = mock.patch.object(client, "http", self.http)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_review_prints_data_scope_map_and_playbook(self):
        from hindsight_cli.mental_models import PLAYBOOK
        # When one model is reviewed
        code, out, _ = fakes.invoke(["mental-models", "review", MODEL_ID])
        # Then its data, every sibling's query and the playbook are printed
        self.assertEqual(code, 0)
        self.assertEqual(out, (
            "%s\n"
            "  mode delta  budget 800  size 4000 chars ~1000 tokens"
            "  ratio 1.25\n"
            "  cron %s\n"
            "  query: %s\n"
            "\n"
            "scope map\n"
            "  %s: %s\n"
            "\n"
            "%s\n") % (MODEL_ID, CRON, QUERY,
                       self.SIBLING_ID, self.SIBLING_QUERY, PLAYBOOK))
        self.http.assert_done()

    def test_review_without_ids_covers_all_models_playbook_once(self):
        from hindsight_cli.mental_models import PLAYBOOK
        # When review is run with no ids
        code, out, _ = fakes.invoke(["mental-models", "review"])
        # Then every model gets a data block, no scope map, one playbook
        self.assertEqual(code, 0)
        self.assertEqual(out, (
            "%s\n"
            "  mode delta  budget 800  size 4000 chars ~1000 tokens"
            "  ratio 1.25\n"
            "  cron %s\n"
            "  query: %s\n"
            "\n"
            "%s\n"
            "  mode delta  budget 800  size 100 chars ~25 tokens"
            "  ratio 0.03\n"
            "  cron %s\n"
            "  query: %s\n"
            "\n"
            "%s\n") % (MODEL_ID, CRON, QUERY,
                       self.SIBLING_ID, CRON, self.SIBLING_QUERY, PLAYBOOK))
        self.http.assert_done()

    def test_review_of_an_unknown_model_dies(self):
        # When the reviewed id is not in the bank
        code, out, err = fakes.invoke(
            ["mental-models", "review", "no-such-model"])
        # Then the command dies naming the id
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertEqual(err, "  ❌ no mental model 'no-such-model'\n")


NOW = datetime.datetime(2026, 8, 26, 12, 0, tzinfo=datetime.timezone.utc)


class ReviewDuplicatesTest(unittest.TestCase):
    RULE = "Never commit or push without an explicit commit instruction."
    NEAR = "Never commit or push without their explicit commit instruction."
    SIBLING_ID = "collaboration"

    def setUp(self):
        items = {"items": [
            {"id": MODEL_ID, "max_tokens": 800, "source_query": QUERY,
             "content": "## Rules\n\n%s\n\nComments describe the current"
                        " state only, never how the code got there.\n"
                        % self.RULE,
             "trigger": dict(FULL_TRIGGER), "last_refreshed_at": None,
             "last_memory_seen_at": None},
            {"id": self.SIBLING_ID, "max_tokens": 800,
             "source_query": "How much autonomy does this user want?",
             "content": "## Rules\n\n%s\n\nAsk before anything with a blast"
                        " radius you cannot cheaply undo.\n" % self.NEAR,
             "trigger": dict(FULL_TRIGGER), "last_refreshed_at": None,
             "last_memory_seen_at": None},
        ]}
        self.http = fakes.FakeHttp(
            [("GET %s?detail=full" % MM_URL, json.dumps(items))])
        patcher = mock.patch.object(client, "http", self.http)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_review_names_a_rule_two_models_both_carry(self):
        # When every model is reviewed and two of them state the same rule
        code, out, _ = fakes.invoke(["mental-models", "review"])
        # Then the pair is named with both wordings, so one can own it
        self.assertEqual(code, 0)
        self.assertIn(
            "duplicates\n"
            "  %s and %s both carry:\n"
            "    %s\n"
            "    %s\n" % (MODEL_ID, self.SIBLING_ID, self.RULE, self.NEAR),
            out)
        self.http.assert_done()


class AuditTest(unittest.TestCase):
    def _audit(self, models):
        self.http = fakes.FakeHttp([
            ("GET %s?detail=full" % MM_URL, json.dumps({"items": models}))])
        with mock.patch.object(client, "http", self.http), \
                mock.patch.object(shell, "now_utc",
                                  mock.Mock(return_value=NOW)):
            return fakes.invoke(["mental-models", "audit"])

    def test_audit_prints_a_data_block_per_model(self):
        chars = 3400
        budget = 800
        model = {"id": MODEL_ID, "max_tokens": budget, "content": "x" * chars,
                 "trigger": dict(FULL_TRIGGER),
                 "last_refreshed_at": "2026-08-26T09:00:00+00:00",
                 "last_memory_seen_at": "2026-08-26T07:00:00+00:00"}
        # When audit runs over one healthy scheduled model
        code, out, _ = self._audit([model])
        # Then one raw data block prints and no hint fires
        self.assertEqual(code, 0)
        self.assertEqual(out, (
            "auditing 1 models, 0 hints (no closing \"audited\" line = your view lost the tail)\n"
            "\n"
            "%s\n"
            "  mode delta  budget %d  size %d chars ~%d tokens  ratio 1.06\n"
            "  cron %s  last refreshed 3h  last memory seen 5h\n"
            "  0 scheduled fires since last refresh\n"
            "\n"
            "audited 1 models, 0 hints (no opening \"auditing\" line = your view lost the head)\n")
            % (MODEL_ID, budget, chars, chars // 4, CRON))

    def test_audit_empty_bank_prints_no_mental_models(self):
        # When audit runs over an empty bank
        code, out, _ = self._audit([])
        # Then it says so and raises no hint
        self.assertEqual(code, 0)
        self.assertEqual(out, "no mental models\n")

    def test_audit_never_refreshed_model_omits_the_fires_line(self):
        budget = 800
        model = {"id": MODEL_ID, "max_tokens": budget, "content": "",
                 "trigger": dict(FULL_TRIGGER),
                 "last_refreshed_at": None, "last_memory_seen_at": None}
        # When a scheduled model has never refreshed
        code, out, _ = self._audit([model])
        # Then ages read never and no fire count is computable
        self.assertEqual(code, 0)
        self.assertEqual(out, (
            "auditing 1 models, 0 hints (no closing \"audited\" line = your view lost the tail)\n"
            "\n"
            "%s\n"
            "  mode delta  budget %d  size 0 chars ~0 tokens  ratio 0.00\n"
            "  cron %s  last refreshed never  last memory seen never\n"
            "\n"
            "audited 1 models, 0 hints (no opening \"auditing\" line = your view lost the head)\n")
            % (MODEL_ID, budget, CRON))

    def test_audit_hints_no_schedule(self):
        budget = 800
        cronless = {key: value for key, value in FULL_TRIGGER.items()
                    if key != "refresh_cron"}
        model = {"id": MODEL_ID, "max_tokens": budget, "content": "",
                 "trigger": cronless,
                 "last_refreshed_at": "2026-08-24T12:00:00+00:00",
                 "last_memory_seen_at": "2026-08-26T09:00:00+00:00"}
        # When a model has no cron
        code, out, _ = self._audit([model])
        # Then the block says no cron, the hint fires and audit exits 1
        self.assertEqual(code, 1)
        self.assertEqual(out, (
            "auditing 1 models, 1 hints: %s (no closing \"audited\" line = your view lost the tail)\n"
            "\n"
            "%s\n"
            "  mode delta  budget %d  size 0 chars ~0 tokens  ratio 0.00\n"
            "  no cron  last refreshed 2d  last memory seen 3h\n"
            "  hint: no schedule\n"
            "\n"
            "audited 1 models, 1 hints: %s (no opening \"auditing\" line = your view lost the head)\n") % (MODEL_ID, MODEL_ID, budget, MODEL_ID))

    def test_audit_hints_over_budget(self):
        chars = 6000
        budget = 800
        model = {"id": MODEL_ID, "max_tokens": budget, "content": "x" * chars,
                 "trigger": dict(FULL_TRIGGER),
                 "last_refreshed_at": "2026-08-26T09:00:00+00:00",
                 "last_memory_seen_at": "2026-08-26T09:00:00+00:00"}
        # When a model sits at 1.5x its budget or more
        code, out, _ = self._audit([model])
        # Then the budget hint fires and audit exits 1
        self.assertEqual(code, 1)
        self.assertEqual(out, (
            "auditing 1 models, 1 hints: %s (no closing \"audited\" line = your view lost the tail)\n"
            "\n"
            "%s\n"
            "  mode delta  budget %d  size %d chars ~%d tokens  ratio 1.88\n"
            "  cron %s  last refreshed 3h  last memory seen 3h\n"
            "  0 scheduled fires since last refresh\n"
            "  hint: over budget; run: atk run hindsight mental-models"
            " review %s\n"
            "\n"
            "audited 1 models, 1 hints: %s (no opening \"auditing\" line = your view lost the head)\n")
            % (MODEL_ID, MODEL_ID, budget, chars, chars // 4, CRON, MODEL_ID,
               MODEL_ID))

    def test_audit_hints_missed_scheduled_fires(self):
        budget = 800
        hourly = "0 * * * *"
        model = {"id": MODEL_ID, "max_tokens": budget, "content": "",
                 "trigger": {**FULL_TRIGGER, "refresh_cron": hourly},
                 "last_refreshed_at": "2026-08-26T06:30:00+00:00",
                 "last_memory_seen_at": "2026-08-26T11:00:00+00:00"}
        # When two or more scheduled fires passed since the last refresh
        code, out, _ = self._audit([model])
        # Then the fires hint names the quiet-scope caveat and audit exits 1
        self.assertEqual(code, 1)
        self.assertEqual(out, (
            "auditing 1 models, 1 hints: %s (no closing \"audited\" line = your view lost the tail)\n"
            "\n"
            "%s\n"
            "  mode delta  budget %d  size 0 chars ~0 tokens  ratio 0.00\n"
            "  cron %s  last refreshed 5h  last memory seen 1h\n"
            "  6 scheduled fires since last refresh\n"
            "  hint: scheduled refreshes are not landing; a quiet scope"
            " skips legitimately; judge against last memory seen\n"
            "\n"
            "audited 1 models, 1 hints: %s (no opening \"auditing\" line = your view lost the head)\n")
            % (MODEL_ID, MODEL_ID, budget, hourly, MODEL_ID))

    def test_audit_exits_1_when_any_model_hints(self):
        budget = 800
        second_id = "testing-style"
        stamp = "2026-08-26T09:00:00+00:00"
        healthy = {"id": MODEL_ID, "max_tokens": budget, "content": "",
                   "trigger": dict(FULL_TRIGGER),
                   "last_refreshed_at": stamp, "last_memory_seen_at": stamp}
        cronless = {"id": second_id, "max_tokens": budget, "content": "",
                    "trigger": {key: value for key, value
                                in FULL_TRIGGER.items()
                                if key != "refresh_cron"},
                    "last_refreshed_at": stamp, "last_memory_seen_at": stamp}
        # When one of two models raises a hint
        code, out, _ = self._audit([healthy, cronless])
        # Then blocks print in order, blank-line separated, and audit exits 1
        self.assertEqual(code, 1)
        self.assertEqual(out, (
            "auditing 2 models, 1 hints: %s (no closing \"audited\" line = your view lost the tail)\n"
            "\n"
            "%s\n"
            "  mode delta  budget %d  size 0 chars ~0 tokens  ratio 0.00\n"
            "  cron %s  last refreshed 3h  last memory seen 3h\n"
            "  0 scheduled fires since last refresh\n"
            "\n"
            "%s\n"
            "  mode delta  budget %d  size 0 chars ~0 tokens  ratio 0.00\n"
            "  no cron  last refreshed 3h  last memory seen 3h\n"
            "  hint: no schedule\n"
            "\n"
            "audited 2 models, 1 hints: %s (no opening \"auditing\" line = your view lost the head)\n")
            % (second_id, MODEL_ID, budget, CRON, second_id, budget,
               second_id))


if __name__ == "__main__":
    unittest.main()
