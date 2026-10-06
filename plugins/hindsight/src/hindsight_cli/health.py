"""The health command: one line when the bank is healthy, an alarm when not."""
import collections
import datetime
import json
import urllib.error

from . import client, shell

ERROR_CHARS = 160
FAILURE_WINDOW = datetime.timedelta(hours=24)
FAILURE_ALARM = 3
STUCK_AFTER = datetime.timedelta(hours=1)


def _ops_url(cfg):
    return "%s/v1/default/banks/%s/operations" % (cfg.url, cfg.bank)


def _ops(cfg, query):
    return json.loads(client.http("GET", "%s?%s" % (_ops_url(cfg), query)))


def _at(stamp):
    return datetime.datetime.fromisoformat(stamp)


def _utc(stamp):
    return _at(stamp).strftime("%Y-%m-%d %H:%M UTC")


def _failure_lines(cfg, failed):
    types = collections.Counter(op["task_type"] for op in failed)
    first = min(op["updated_at"] for op in failed)
    error = failed[0]["error_message"]
    if len(error) > ERROR_CHARS:
        error = error[:ERROR_CHARS] + "…"
    return ["  %d operations failed in the last 24h (%s), first at %s"
            % (len(failed),
               ", ".join("%s %d" % kv for kv in sorted(types.items())),
               _utc(first)),
            "  latest error: %s" % error,
            "  failed operations: %s?status=failed" % _ops_url(cfg)]


def _recent_failures(cfg, since):
    failed, offset = [], 0
    while True:
        body = _ops(cfg, "status=failed&exclude_parents=true&limit=100"
                         "&offset=%d" % offset)
        ops = body["operations"]
        failed += [op for op in ops if _at(op["updated_at"]) >= since]
        offset += len(ops)
        # Pages run newest first, so a page that reaches past the window ends the read.
        if offset >= body["total"] or _at(ops[-1]["created_at"]) < since:
            return failed


def _stuck_lines(cfg, now):
    total = _ops(cfg, "status=pending&limit=1")["total"]
    if not total:
        return []
    oldest = _ops(cfg, "status=pending&limit=1&offset=%d"
                       % (total - 1))["operations"][0]["created_at"]
    if _at(oldest) >= now - STUCK_AFTER:
        return []
    return ["  %d operations pending, the oldest since %s" % (total, _utc(oldest)),
            "  pending operations: %s?status=pending" % _ops_url(cfg)]


def run(cfg):
    try:
        return _check(cfg)
    except urllib.error.URLError as error:
        print("🚨 HINDSIGHT UNHEALTHY")
        print("  cannot reach Hindsight at %s: %s" % (cfg.url, error))
        return 1


def _check(cfg):
    now = shell.now_utc()
    failed = _recent_failures(cfg, now - FAILURE_WINDOW)
    alarm = _failure_lines(cfg, failed) if len(failed) >= FAILURE_ALARM else []
    alarm += _stuck_lines(cfg, now)
    if alarm:
        print("🚨 HINDSIGHT UNHEALTHY")
        print("\n".join(alarm))
    else:
        print("hindsight healthy: %d operations failed in the last 24h,"
              " nothing pending over 1h" % len(failed))
    backlog = _ops(cfg, "status=failed&type=retain&limit=1")["total"]
    if backlog:
        print("  %d failed retains remain in the operation log; replay or"
              " delete them" % backlog)
    return 1 if alarm else 0
