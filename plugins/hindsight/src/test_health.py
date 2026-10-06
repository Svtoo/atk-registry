#!/usr/bin/env python3
"""Tests for the health command: failed, stuck and unreachable alarms."""
import datetime
import json
import unittest
import urllib.error
from unittest import mock

import fakes
from hindsight_cli import client, shell

OPS_URL = "http://localhost:8888/v1/default/banks/default/operations"
FAILED_PAGE = "GET %s?status=failed&exclude_parents=true&limit=100&offset=%d"
PENDING_COUNT = "GET %s?status=pending&limit=1" % OPS_URL
PENDING_OLDEST = "GET %s?status=pending&limit=1&offset=%d"
SAVES_COUNT = "GET %s?status=failed&type=retain&limit=1" % OPS_URL
NOW = datetime.datetime(2026, 10, 6, 12, 0, tzinfo=datetime.timezone.utc)


def failure(task_type, at, error):
    return {"task_type": task_type, "created_at": at, "updated_at": at,
            "status": "failed", "error_message": error}


def pending(at):
    return {"task_type": "retain", "created_at": at, "updated_at": at,
            "status": "pending", "error_message": None}


def page(operations, total=None):
    return json.dumps({"total": len(operations) if total is None else total,
                       "operations": operations})


class HealthTest(unittest.TestCase):
    def _health(self, script):
        self.http = fakes.FakeHttp(script)
        with mock.patch.object(client, "http", self.http), \
                mock.patch.object(shell, "now_utc",
                                  mock.Mock(return_value=NOW)):
            result = fakes.invoke(["health"])
        self.http.assert_done()
        return result

    def test_a_quiet_bank_reports_healthy(self):
        # When health runs over a bank with no failures and nothing pending
        code, out, _ = self._health([
            (FAILED_PAGE % (OPS_URL, 0), page([])),
            (PENDING_COUNT, page([])),
            (SAVES_COUNT, page([]))])
        # Then one healthy line prints and health exits 0
        self.assertEqual(code, 0)
        self.assertEqual(out, "hindsight healthy: 0 operations failed in the"
                              " last 24h, nothing pending over 1h\n")

    def test_three_failures_in_24h_raise_the_alarm(self):
        latest = "NotFoundError: No allowed providers " + "x" * 300
        older = "RateLimitError: 429"
        failed = [failure("retain", "2026-10-06T11:00:00+00:00", latest),
                  failure("retain", "2026-10-06T10:00:00+00:00", older),
                  failure("refresh_mental_model", "2026-10-06T09:00:00+00:00",
                          older)]
        # When three operations failed within the last 24h
        code, out, _ = self._health([
            (FAILED_PAGE % (OPS_URL, 0), page(failed)),
            (PENDING_COUNT, page([])),
            (SAVES_COUNT, page([]))])
        # Then the alarm names the count by type, when it began and the latest error
        self.assertEqual(code, 1)
        self.assertEqual(out, (
            "🚨 HINDSIGHT UNHEALTHY\n"
            "  3 operations failed in the last 24h (refresh_mental_model 1,"
            " retain 2), first at 2026-10-06 09:00 UTC\n"
            "  latest error: %s…\n"
            "  failed operations: %s?status=failed\n")
            % (latest[:160], OPS_URL))

    def test_failures_are_read_page_by_page_up_to_the_24h_edge(self):
        error = "NotFoundError: 404"
        recent = failure("retain", "2026-10-06T11:00:00+00:00", error)
        old = failure("retain", "2026-10-04T11:00:00+00:00", error)
        # When the last 24h hold 101 failures and older pages remain
        code, out, _ = self._health([
            (FAILED_PAGE % (OPS_URL, 0), page([recent] * 100, total=250)),
            (FAILED_PAGE % (OPS_URL, 100),
             page([recent] + [old] * 99, total=250)),
            (PENDING_COUNT, page([])),
            (SAVES_COUNT, page([]))])
        # Then all 101 are counted and no page past the edge is read
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines()[1],
                         "  101 operations failed in the last 24h (retain 101),"
                         " first at 2026-10-06 11:00 UTC")

    def test_failures_below_three_or_older_than_24h_stay_healthy(self):
        error = "RateLimitError: 429"
        failed = [failure("retain", "2026-10-06T11:00:00+00:00", error),
                  failure("retain", "2026-10-05T12:30:00+00:00", error),
                  failure("retain", "2026-10-05T11:30:00+00:00", error)]
        # When two failures fall inside the last 24h and one before it
        code, out, _ = self._health([
            (FAILED_PAGE % (OPS_URL, 0), page(failed)),
            (PENDING_COUNT, page([])),
            (SAVES_COUNT, page([]))])
        # Then health counts only the recent two and stays below the alarm
        self.assertEqual(code, 0)
        self.assertEqual(out, "hindsight healthy: 2 operations failed in the"
                              " last 24h, nothing pending over 1h\n")

    def test_an_unreachable_service_raises_the_alarm(self):
        refused = urllib.error.URLError("Connection refused")
        # When the API cannot be reached
        with mock.patch.object(client, "http", mock.Mock(side_effect=refused)):
            code, out, _ = fakes.invoke(["health"])
        # Then the alarm names the address and the error
        self.assertEqual(code, 1)
        self.assertEqual(out, (
            "🚨 HINDSIGHT UNHEALTHY\n"
            "  cannot reach Hindsight at http://localhost:8888: %s\n") % refused)

    def test_failed_retains_left_in_the_log_are_reported_without_alarm(self):
        total = 115
        # When old failed retains remain in the operation log
        code, out, _ = self._health([
            (FAILED_PAGE % (OPS_URL, 0), page([])),
            (PENDING_COUNT, page([])),
            (SAVES_COUNT, page([failure("retain", "2026-10-02T01:30:00+00:00",
                                        "NotFoundError: 404")], total=total))])
        # Then health stays healthy and names the backlog
        self.assertEqual(code, 0)
        self.assertEqual(out, (
            "hindsight healthy: 0 operations failed in the last 24h,"
            " nothing pending over 1h\n"
            "  %d failed retains remain in the operation log; replay or"
            " delete them\n") % total)

    def test_work_pending_over_an_hour_raises_the_alarm(self):
        oldest = pending("2026-10-06T10:30:00+00:00")
        total = 9
        # When the oldest of nine pending operations waits ninety minutes
        code, out, _ = self._health([
            (FAILED_PAGE % (OPS_URL, 0), page([])),
            (PENDING_COUNT, page([pending("2026-10-06T11:59:00+00:00")],
                                 total=total)),
            (PENDING_OLDEST % (OPS_URL, total - 1), page([oldest], total=total)),
            (SAVES_COUNT, page([]))])
        # Then the alarm says work is stuck and since when
        self.assertEqual(code, 1)
        self.assertEqual(out, (
            "🚨 HINDSIGHT UNHEALTHY\n"
            "  %d operations pending, the oldest since 2026-10-06 10:30 UTC\n"
            "  pending operations: %s?status=pending\n") % (total, OPS_URL))

    def test_work_pending_under_an_hour_stays_healthy(self):
        total = 5
        # When the oldest pending operation waits thirty minutes
        code, out, _ = self._health([
            (FAILED_PAGE % (OPS_URL, 0), page([])),
            (PENDING_COUNT, page([pending("2026-10-06T11:59:00+00:00")],
                                 total=total)),
            (PENDING_OLDEST % (OPS_URL, total - 1),
             page([pending("2026-10-06T11:30:00+00:00")], total=total)),
            (SAVES_COUNT, page([]))])
        # Then health reports healthy
        self.assertEqual(code, 0)
        self.assertEqual(out, "hindsight healthy: 0 operations failed in the"
                              " last 24h, nothing pending over 1h\n")


if __name__ == "__main__":
    unittest.main()
