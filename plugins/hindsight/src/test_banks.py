#!/usr/bin/env python3
"""Tests for the banks command: listing and guarded deletion."""
import json
import os
import unittest
from unittest import mock

import fakes
from hindsight_cli import client, shell

BANKS_URL = "http://localhost:8888/v1/default/banks"
TWO_BANKS = json.dumps({"banks": [
    {"bank_id": "scratch", "fact_count": 12, "last_write_at": None},
    {"bank_id": "default", "fact_count": 18624,
     "last_write_at": "2026-08-21T12:00:00Z"},
]})


class BanksListTest(unittest.TestCase):
    def setUp(self):
        self.http = mock.Mock(return_value=TWO_BANKS)
        patcher = mock.patch.object(client, "http", self.http)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_lists_banks_by_fact_count_marking_the_active_one(self):
        # When banks are listed with the default bank active
        code, out, _ = fakes.invoke(["banks"])
        # Then rows sort by fact count with the agent's bank marked and a
        # never-written bank labelled
        self.assertEqual(code, 0)
        self.assertEqual(out, (
            "   18624  default  2026-08-21T12:00:00Z  <- this agent\n"
            "      12  scratch  never written\n"))

    def test_empty_bank_list(self):
        self.http.return_value = json.dumps({"banks": []})
        code, out, _ = fakes.invoke(["banks", "list"])
        self.assertEqual(code, 0)
        self.assertEqual(out, "no banks\n")

    def test_unreachable_service_dies_cleanly(self):
        self.http.side_effect = OSError("connection refused")
        code, _, err = fakes.invoke(["banks"])
        self.assertEqual(code, 1)
        self.assertIn("Cannot reach Hindsight", err)
        self.assertNotIn("Traceback", err)


class BanksDeleteTest(unittest.TestCase):
    def setUp(self):
        self.http = mock.Mock(return_value="")
        self.confirm = mock.Mock(return_value=True)
        for module, name, value in ((client, "http", self.http),
                                    (shell, "confirm", self.confirm)):
            patcher = mock.patch.object(module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_delete_requires_bank_names(self):
        code, _, err = fakes.invoke(["banks", "delete"])
        self.assertEqual(code, 1)
        self.assertIn("usage", err)
        self.http.assert_not_called()

    def test_declined_confirm_deletes_nothing(self):
        self.confirm.return_value = False
        code, _, err = fakes.invoke(["banks", "delete", "scratch"])
        self.assertEqual(code, 1)
        self.assertIn("Aborted", err)
        self.http.assert_not_called()

    def test_confirmed_delete_calls_the_api_per_bank(self):
        bank = "scratch"
        code, out, _ = fakes.invoke(["banks", "delete", bank])
        self.assertEqual(code, 0)
        self.assertIn("✓ deleted %s" % bank, out)
        self.http.assert_called_once_with(
            "DELETE", "http://localhost:8888/v1/default/banks/%s" % bank,
            timeout=60)

    def test_each_bank_needs_its_own_confirm(self):
        first, second = "scratch", "other"
        # Given a yes for the first bank and a no for the second
        self.confirm.side_effect = [True, False]
        code, out, err = fakes.invoke(["banks", "delete", first, second])
        # Then only the confirmed bank is deleted before the run aborts
        self.assertEqual(code, 1)
        self.assertIn("✓ deleted %s" % first, out)
        self.assertIn("Aborted", err)
        self.assertEqual(self.http.call_count, 1)
        self.assertIn(first, self.http.call_args[0][1])

    def test_failed_delete_stops_the_run(self):
        self.http.side_effect = OSError("boom")
        code, _, err = fakes.invoke(["banks", "delete", "scratch", "other"])
        self.assertEqual(code, 1)
        self.assertIn("Nothing further was attempted", err)
        self.assertEqual(self.http.call_count, 1)


if __name__ == "__main__":
    unittest.main()
