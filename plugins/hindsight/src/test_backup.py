#!/usr/bin/env python3
"""Tests for the backup command: guards, dump promotion, retention, failure."""
import datetime
import errno
import json
import fcntl
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import fakes
from hindsight_cli import client, config, shell
from test_ops import INSTANCE_JSON

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
HOLDER = """
import sys, time
sys.path.insert(0, %r)
from hindsight_cli import config, shell
with shell.backup_lock(config.Config({}, plugin_dir=%r)):
    print("held", flush=True)
    time.sleep(30)
"""

BACKUP_AT = datetime.datetime(2026, 8, 21, 18, 30, 0)
DATED_NAME = "hindsight_backup_2026-08-21_1830_hs0.9.2.dump"
DUMP_BYTES = b"PGDMP fake archive bytes"

SERVICE_UP = ("docker exec hindsight true", fakes.ok())
INSTANCE = ("instance.json", fakes.ok(INSTANCE_JSON))
PG_DUMP = ("pg_dump", fakes.ok(DUMP_BYTES))
TOC_COPY = ("docker cp", fakes.ok())
TOC_LIST = ("pg_restore --list /tmp/toc-check.dump", fakes.ok())
TOC_RM = ("rm -f /tmp/toc-check.dump", fakes.ok())


class BackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.backup_dir = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        # An isolated plugin dir, so a test never takes the lock of the
        # hindsight installed on this machine.
        self.plugin_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.plugin_tmp.cleanup)
        plugin_patch = mock.patch.object(config, "PLUGIN_DIR", self.plugin_tmp.name)
        plugin_patch.start()
        self.addCleanup(plugin_patch.stop)
        self.environ = {"HINDSIGHT_BACKUP_DIR": self.backup_dir}
        self.notify = mock.Mock()
        self.http = mock.Mock(return_value=json.dumps({"api_version": "0.9.2"}))
        http_patch = mock.patch.object(client, "http", self.http)
        http_patch.start()
        self.addCleanup(http_patch.stop)
        for name, value in (("now", lambda: BACKUP_AT), ("notify", self.notify)):
            patcher = mock.patch.object(shell, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        env_patch = mock.patch.dict(os.environ, self.environ, clear=False)
        env_patch.start()
        self.addCleanup(env_patch.stop)

    def use_script(self, script):
        fake = fakes.FakeRun(script)
        patcher = mock.patch.object(shell, "run", fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    def write_dump(self, name, age_hours):
        path = os.path.join(self.backup_dir, name)
        open(path, "w").close()
        mtime = (BACKUP_AT - datetime.timedelta(hours=age_hours)).timestamp()
        os.utime(path, (mtime, mtime))
        return path

    def test_unset_backup_dir_skips_quietly(self):
        # Given no backup dir configured
        fake = self.use_script([])
        with mock.patch.dict(os.environ, {"HINDSIGHT_BACKUP_DIR": ""}):
            code, out, _ = fakes.invoke(["backup"])
        # Then nothing runs and the command still succeeds
        self.assertEqual(code, 0)
        self.assertIn("HINDSIGHT_BACKUP_DIR is not set", out)
        self.assertEqual(fake.calls, [])

    def test_if_stale_skips_while_fresh(self):
        # Given a dump two hours old
        self.write_dump("hindsight_backup_2026-08-21_1600.dump", age_hours=2)
        fake = self.use_script([])
        # When backup runs with --if-stale
        code, out, err = fakes.invoke(["backup", "--if-stale"])
        # Then it exits silently without touching anything
        self.assertEqual(code, 0)
        self.assertEqual(out, "")
        self.assertEqual(err, "")
        self.assertEqual(fake.calls, [])

    def test_if_stale_dumps_once_stale(self):
        # Given the newest dump is over a day old
        self.write_dump("hindsight_backup_2026-08-20_1600.dump", age_hours=26)
        fake = self.use_script(
            [SERVICE_UP, INSTANCE, PG_DUMP, TOC_COPY, TOC_LIST, TOC_RM])
        # When backup runs with --if-stale
        code, out, _ = fakes.invoke(["backup", "--if-stale"])
        # Then a new dated dump is produced
        self.assertEqual(code, 0)
        self.assertIn(DATED_NAME, out)
        fake.assert_done()

    def test_full_run_writes_and_promotes_the_dated_dump(self):
        # The discard-on-TOC-failure test below pins that promotion requires
        # the TOC check; this pins the happy path and the exact dump command.
        fake = self.use_script(
            [SERVICE_UP, INSTANCE, PG_DUMP, TOC_COPY, TOC_LIST, TOC_RM])
        # When a plain backup runs
        code, out, _ = fakes.invoke(["backup"])
        # Then the dated dump holds the pg_dump output, the partial is gone,
        # and the lock is released
        self.assertEqual(code, 0)
        dump_path = os.path.join(self.backup_dir, DATED_NAME)
        with open(dump_path, "rb") as fh:
            self.assertEqual(fh.read(), DUMP_BYTES)
        self.assertEqual(sorted(os.listdir(self.backup_dir)), [DATED_NAME])
        self.assertIn("✅", out)
        self.assertEqual(fake.call_at("pg_dump"), [
            "docker", "exec", "-e", "PGPASSWORD=hindsight", "hindsight",
            "/home/hindsight/.pg0/installation/18.1.0/bin/pg_dump",
            "-h", "localhost", "-p", "5432", "-U", "hindsight",
            "-d", "hindsight", "-Fc"])
        fake.assert_done()

    def test_a_partial_left_by_a_killed_run_is_swept(self):
        # Given the half-written dump a killed run leaves behind
        stale = os.path.join(self.backup_dir,
                             "hindsight_backup_2026-08-20_0900.dump.partial")
        with open(stale, "wb") as fh:
            fh.write(b"half a dump")
        fake = self.use_script(
            [SERVICE_UP, INSTANCE, PG_DUMP, TOC_COPY, TOC_LIST, TOC_RM])
        # When the next backup runs
        code, out, _ = fakes.invoke(["backup"])
        # Then it is gone and said so, and the new dump is the only file left
        self.assertEqual(code, 0)
        self.assertIn("leftover", out)
        self.assertEqual(os.listdir(self.backup_dir), [DATED_NAME])
        fake.assert_done()

    def test_a_version_that_cannot_be_read_is_named_in_the_dump(self):
        # Given a server that will not say what it is
        self.http.side_effect = OSError("no answer")
        fake = self.use_script(
            [SERVICE_UP, INSTANCE, PG_DUMP, TOC_COPY, TOC_LIST, TOC_RM])
        code, out, err = fakes.invoke(["backup"])
        # Then the backup still happens and the gap is visible in the name
        self.assertEqual(code, 0)
        self.assertEqual(os.listdir(self.backup_dir),
                         ["hindsight_backup_2026-08-21_1830_hsunknown.dump"])
        self.assertIn("version", err)
        fake.assert_done()

    def test_unwritable_lock_location_dies_cleanly(self):
        fake = self.use_script([SERVICE_UP])
        # Given the lock file cannot be opened at all
        with mock.patch("os.open", side_effect=PermissionError("denied")):
            code, _, err = fakes.invoke(["backup"])
        # Then the run dies with a message instead of a traceback
        self.assertEqual(code, 1)
        self.assertIn("lock", err)
        self.assertNotIn("Traceback", err)
        self.notify.assert_called_once()
        fake.assert_done()

    def test_retention_prunes_same_day_duplicates_keeping_sparse_history(self):
        # Given an older same-day dump and a months-old dump on an otherwise
        # sparse history
        same_day = self.write_dump(
            "hindsight_backup_2026-08-21_0900.dump", age_hours=30)
        months_old = self.write_dump(
            "hindsight_backup_2026-04-01_0900.dump", age_hours=3000)
        fake = self.use_script(
            [SERVICE_UP, INSTANCE, PG_DUMP, TOC_COPY, TOC_LIST, TOC_RM])
        # When a backup succeeds
        code, out, _ = fakes.invoke(["backup"])
        # Then the same-day duplicate is pruned, while the months-old dump
        # stays within the seven newest days that hold dumps
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(same_day))
        self.assertTrue(os.path.exists(months_old))
        self.assertIn("Pruned", out)
        fake.assert_done()

    def test_failed_dump_leaves_no_file_and_notifies(self):
        existing = self.write_dump(
            "hindsight_backup_2026-08-20_0900.dump", age_hours=30)
        fake = self.use_script([SERVICE_UP, INSTANCE, ("pg_dump", fakes.fail())])
        # When pg_dump fails
        code, _, _ = fakes.invoke(["backup"])
        # Then the run fails, no partial or dated file remains, the existing
        # dump is untouched, the lock is released, and a notification fires
        self.assertNotEqual(code, 0)
        self.assertEqual(sorted(os.listdir(self.backup_dir)),
                         [os.path.basename(existing)])
        self.notify.assert_called_once()
        fake.assert_done()

    def test_failed_toc_check_discards_the_dump(self):
        fake = self.use_script(
            [SERVICE_UP, INSTANCE, PG_DUMP, TOC_COPY,
             ("pg_restore --list", fakes.fail())])
        # When the table-of-contents check fails
        code, _, _ = fakes.invoke(["backup"])
        # Then nothing is promoted and a notification fires
        self.assertNotEqual(code, 0)
        self.assertEqual(os.listdir(self.backup_dir), [])
        self.notify.assert_called_once()
        fake.assert_done()

    def hold_the_lock(self, payload):
        """Takes the real lock the way a running backup holds it."""
        path = shell.backup_lock_path(config.Config(os.environ))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.write(fd, payload.encode())
        return path

    def test_a_live_run_stops_the_second_backup(self):
        # Given a backup already holding the lock
        self.hold_the_lock("pid 4711 since 2026-08-21 18:29:00\n")
        fake = self.use_script([SERVICE_UP])
        # When another backup starts
        code, _, err = fakes.invoke(["backup"])
        # Then it dies loudly, names the holder, and notifies
        self.assertEqual(code, 1)
        self.assertIn("Another backup is already running", err)
        self.assertIn("pid 4711 since 2026-08-21 18:29:00", err)
        self.assertIn("ps -p 4711", err)
        self.notify.assert_called_once()
        fake.assert_done()

    def test_a_second_process_cannot_hold_the_lock_at_the_same_time(self):
        # Given another process inside the lock, taken the way a backup takes it
        holder = subprocess.Popen(
            [sys.executable, "-c", HOLDER % (SRC_DIR, self.plugin_tmp.name)],
            stdout=subprocess.PIPE, text=True)
        self.addCleanup(holder.wait)
        self.addCleanup(holder.kill)
        self.assertEqual(holder.stdout.readline().strip(), "held")
        # When this process asks for the same lock, it is refused
        with self.assertRaises(SystemExit):
            with shell.backup_lock(config.Config(os.environ)):
                pass

    def test_a_lock_left_by_a_killed_run_does_not_block_the_next_backup(self):
        # Given the lock file a killed run leaves behind, unheld
        path = shell.backup_lock_path(config.Config(os.environ))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write("pid 4711 since 2026-08-21 18:29:00\n")
        fake = self.use_script(
            [SERVICE_UP, INSTANCE, PG_DUMP, TOC_COPY, TOC_LIST, TOC_RM])
        # When the next backup runs
        code, out, _ = fakes.invoke(["backup"])
        # Then it takes the lock and completes
        self.assertEqual(code, 0)
        self.assertIn(DATED_NAME, out)
        fake.assert_done()

    def test_the_lock_records_the_holder_for_the_next_run_to_report(self):
        fake = self.use_script(
            [SERVICE_UP, INSTANCE, PG_DUMP, TOC_COPY, TOC_LIST, TOC_RM])
        with mock.patch.object(os, "getpid", lambda: 4711):
            code, _, _ = fakes.invoke(["backup"])
        # Then the lock carries who held it and when
        self.assertEqual(code, 0)
        with open(shell.backup_lock_path(config.Config(os.environ))) as fh:
            self.assertEqual(fh.read().strip(),
                             "pid 4711 since 2026-08-21 18:30:00")

    def test_the_record_replaces_a_longer_one_left_by_a_killed_run(self):
        # Given a lock file whose previous record is longer than the new one
        path = shell.backup_lock_path(config.Config(os.environ))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write("pid 999999 since 2026-08-20 09:00:00 on a much longer line\n")
        fake = self.use_script(
            [SERVICE_UP, INSTANCE, PG_DUMP, TOC_COPY, TOC_LIST, TOC_RM])
        # When the next backup takes the lock
        with mock.patch.object(os, "getpid", lambda: 4711):
            code, _, _ = fakes.invoke(["backup"])
        # Then the file holds this run and nothing of the last one
        self.assertEqual(code, 0)
        with open(path) as fh:
            self.assertEqual(fh.read().strip(),
                             "pid 4711 since 2026-08-21 18:30:00")
        fake.assert_done()

    def test_a_stale_lock_directory_from_the_old_scheme_is_ignored(self):
        # Given the directory the previous locking scheme left in the dumps folder
        os.mkdir(os.path.join(self.backup_dir, ".backup.lock"))
        fake = self.use_script(
            [SERVICE_UP, INSTANCE, PG_DUMP, TOC_COPY, TOC_LIST, TOC_RM])
        code, out, _ = fakes.invoke(["backup"])
        # Then it means nothing to the run
        self.assertEqual(code, 0)
        self.assertIn(DATED_NAME, out)
        fake.assert_done()

    def test_service_down_dies_and_notifies(self):
        # Given the container is not running
        fake = self.use_script([("docker exec hindsight true", fakes.fail())])
        code, _, err = fakes.invoke(["backup"])
        # Then the run fails loudly and a notification fires
        self.assertEqual(code, 1)
        self.assertIn("not running", err)
        self.notify.assert_called_once()
        fake.assert_done()

    def test_unknown_argument_is_rejected(self):
        fake = self.use_script([])
        code, _, err = fakes.invoke(["backup", "--frobnicate"])
        self.assertEqual(code, 2)
        self.assertNotEqual(err, "")
        self.assertEqual(fake.calls, [])


if __name__ == "__main__":
    unittest.main()
