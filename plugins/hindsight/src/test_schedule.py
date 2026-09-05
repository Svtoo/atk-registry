#!/usr/bin/env python3
"""Tests for the schedule command: launchd job install, removal, and status."""
import os
import sys
import tempfile
import unittest
from unittest import mock

import fakes
from hindsight_cli import config, shell

LABEL = "com.atk.hindsight-backup"
NOT_LOADED = ("launchctl print", fakes.fail())
LOADED = ("launchctl print", fakes.ok())
BOOTOUT = ("launchctl bootout", fakes.ok())
BOOTSTRAP = ("launchctl bootstrap", fakes.ok())


class ScheduleTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.backups = tempfile.TemporaryDirectory()
        self.addCleanup(self.backups.cleanup)
        env = {"HOME": self.home.name,
               "HINDSIGHT_BACKUP_DIR": self.backups.name}
        env_patch = mock.patch.dict(os.environ, env, clear=False)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.plist = os.path.join(
            self.home.name, "Library", "LaunchAgents", LABEL + ".plist")
        self.log = os.path.join(
            self.home.name, "Library", "Logs", "atk-hindsight-backup.log")

    def use_script(self, script):
        fake = fakes.FakeRun(script)
        patcher = mock.patch.object(shell, "run", fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    def test_on_writes_the_plist_and_bootstraps(self):
        fake = self.use_script([NOT_LOADED, BOOTSTRAP, NOT_LOADED])
        # When the schedule is installed on a machine without the job
        code, out, _ = fakes.invoke(["schedule"])
        # Then the plist matches the rendered job and bootstrap ran
        self.assertEqual(code, 0)
        with open(self.plist) as fh:
            self.assertEqual(
                fh.read(), shell.render_plist(LABEL, config.PLUGIN_DIR, self.log))
        self.assertGreater(fake.index_of("launchctl bootstrap"), -1)
        self.assertIn("Newest backup: none", out)

    def test_on_refreshes_a_loaded_job(self):
        fake = self.use_script([LOADED, BOOTOUT, BOOTSTRAP, LOADED])
        # When the schedule is installed over a loaded job
        code, _, _ = fakes.invoke(["schedule"])
        # Then the old job is booted out before the new one bootstraps
        self.assertEqual(code, 0)
        self.assertLess(fake.index_of("launchctl bootout"),
                        fake.index_of("launchctl bootstrap"))
        fake.assert_done()

    def test_off_removes_job_and_plist(self):
        os.makedirs(os.path.dirname(self.plist), exist_ok=True)
        open(self.plist, "a").close()
        fake = self.use_script([LOADED, BOOTOUT])
        code, out, _ = fakes.invoke(["schedule", "off"])
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(self.plist))
        self.assertIn("removed", out)
        fake.assert_done()

    def test_off_without_a_loaded_job_still_removes_the_plist(self):
        os.makedirs(os.path.dirname(self.plist), exist_ok=True)
        open(self.plist, "a").close()
        fake = self.use_script([NOT_LOADED])
        code, _, _ = fakes.invoke(["schedule", "off"])
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(self.plist))
        fake.assert_done()

    def test_status_reports_job_backup_and_log(self):
        newest = "hindsight_backup_2026-08-21_1828.dump"
        open(os.path.join(self.backups.name, newest), "a").close()
        os.makedirs(os.path.dirname(self.log), exist_ok=True)
        log_line = "  ✅ a-backup-line"
        with open(self.log, "w") as fh:
            fh.write(log_line + "\n")
        self.use_script([LOADED])
        code, out, _ = fakes.invoke(["schedule", "status"])
        self.assertEqual(code, 0)
        self.assertIn("Job: loaded", out)
        self.assertIn(newest, out)
        self.assertIn(log_line, out)

    def test_on_without_backup_dir_dies(self):
        self.use_script([])
        with mock.patch.dict(os.environ, {"HINDSIGHT_BACKUP_DIR": ""}):
            code, _, err = fakes.invoke(["schedule"])
        self.assertEqual(code, 1)
        self.assertIn("HINDSIGHT_BACKUP_DIR is not set", err)

    def test_a_platform_without_launchd_says_so(self):
        # Given a machine whose scheduler this command does not speak
        self.use_script([])
        with mock.patch.object(sys, "platform", "linux"):
            code, _, err = fakes.invoke(["schedule"])
        # Then it says so and names what to run instead
        self.assertEqual(code, 1)
        self.assertIn("macOS", err)
        self.assertIn("backup --if-stale", err)

    def test_status_on_such_a_platform_says_the_same(self):
        self.use_script([])
        with mock.patch.object(sys, "platform", "linux"):
            code, _, err = fakes.invoke(["schedule", "status"])
        self.assertEqual(code, 1)
        self.assertIn("macOS", err)

    def test_unknown_argument_dies_with_usage(self):
        self.use_script([])
        code, _, err = fakes.invoke(["schedule", "sideways"])
        self.assertEqual(code, 1)
        self.assertIn("Usage", err)


if __name__ == "__main__":
    unittest.main()
