#!/usr/bin/env python3
"""Tests for the restore command: source selection, the incoming-first swap,
and the invariant that a failed restore never touches the live database."""
import os
import tempfile
import unittest
from unittest import mock

import fakes
from hindsight_cli import client, config, restore, shell
from test_ops import INSTANCE_JSON

NEWEST = "hindsight_backup_2026-08-21_1800.dump"
OLDER = "hindsight_backup_2026-08-20_1800.dump"

INSTANCE = ("instance.json", fakes.ok(INSTANCE_JSON))
STOP_PS = ("ps", fakes.ok("hindsight\n"))
STOP_DOWN = ("down", fakes.ok())
CLEAR_HELPER = ("docker rm -f hindsight-restore", fakes.ok())
COMPOSE_IMAGES = ("--images", fakes.ok("ghcr.io/vectorize-io/hindsight:0.9.1\n"))
RUN_HELPER = ("--shm-size=1g", fakes.ok("abc123\n"))
READY = ("pg_isready", fakes.ok())
COPY_IN = ("docker cp", fakes.ok())
DROP_INCOMING = ("DROP DATABASE IF EXISTS hindsight_incoming", fakes.ok())
CREATE_INCOMING = ("CREATE DATABASE hindsight_incoming", fakes.ok())
PG_RESTORE = ("pg_restore", fakes.ok())
DROP_PREVIOUS_IF = ("DROP DATABASE IF EXISTS hindsight_previous", fakes.ok())
RENAME_LIVE = ("ALTER DATABASE hindsight RENAME TO hindsight_previous", fakes.ok())
RENAME_INCOMING = ("ALTER DATABASE hindsight_incoming RENAME TO hindsight", fakes.ok())
DROP_PREVIOUS = ("DROP DATABASE hindsight_previous", fakes.ok())
REMOVE_HELPER = ("docker rm -f hindsight-restore", fakes.ok())
ID_BEFORE = ("docker inspect", fakes.ok("cid-1\n"))
START_UP = ("up -d", fakes.ok())
ID_AFTER = ("docker inspect", fakes.ok("cid-1\n"))

HAPPY_TAIL = [CLEAR_HELPER, RUN_HELPER, READY, COPY_IN,
              DROP_INCOMING, CREATE_INCOMING, PG_RESTORE, DROP_PREVIOUS_IF,
              RENAME_LIVE, RENAME_INCOMING, DROP_PREVIOUS, REMOVE_HELPER,
              ID_BEFORE, START_UP, ID_AFTER]


class RestoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.backup_dir = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        for name in (NEWEST, OLDER):
            with open(os.path.join(self.backup_dir, name), "w") as fh:
                fh.write("fake dump")
        self.confirm = mock.Mock(return_value=True)
        patches = (
            (shell, "confirm", self.confirm),
            (shell, "sleep", lambda seconds: None),
            (client, "http", mock.Mock(return_value="ok")),
        )
        for module, name, value in patches:
            patcher = mock.patch.object(module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        env = {"HINDSIGHT_BACKUP_DIR": self.backup_dir}
        env_patch = mock.patch.dict(os.environ, env, clear=False)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        volume_ok = mock.patch.object(shell, "require_volume", lambda cfg: None)
        volume_ok.start()
        self.addCleanup(volume_ok.stop)

    def use_script(self, script):
        fake = fakes.FakeRun(script)
        patcher = mock.patch.object(shell, "run", fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    def test_restores_the_newest_dump_through_the_incoming_swap(self):
        fake = self.use_script(
            [COMPOSE_IMAGES, INSTANCE, STOP_PS, STOP_DOWN] + HAPPY_TAIL)
        # When restore runs against the newest dump
        code, out, _ = fakes.invoke(["restore"])
        # Then it succeeds, names the newest dump, restores into the incoming
        # database before any rename, and never mounts the backup folder into
        # the maintenance container
        self.assertEqual(code, 0)
        self.assertIn(NEWEST, out)
        self.assertIn("✅ Restored", out)
        restore_at = fake.index_of("pg_restore")
        rename_at = fake.index_of("RENAME TO hindsight_previous")
        self.assertGreater(rename_at, restore_at)
        helper_run = fake.joined_calls()[fake.index_of("--shm-size=1g")]
        self.assertNotIn(self.backup_dir, helper_run)
        restore_call = fake.call_at("pg_restore")
        self.assertIn("--exit-on-error", restore_call)
        self.assertIn("/tmp/restore.dump", restore_call)
        self.assertEqual(restore_call[restore_call.index("-d") + 1],
                         "hindsight_incoming")
        # Server NOTICE chatter (e.g. from DROP ... IF EXISTS) reads like a
        # failure in the restore output, so every maintenance session mutes it
        drop_call = fake.call_at("DROP DATABASE IF EXISTS hindsight_incoming")
        self.assertIn("PGOPTIONS=-c client_min_messages=warning", drop_call)
        base_compose = shell.compose_cmd(config.Config({}, plugin_dir=config.PLUGIN_DIR))
        self.assertEqual(fake.call_at(" down"), base_compose + ["down"])
        fake.assert_done()

    def test_explicit_file_argument_wins(self):
        explicit = os.path.join(self.backup_dir, OLDER)
        fake = self.use_script(
            [COMPOSE_IMAGES, INSTANCE, STOP_PS, STOP_DOWN] + HAPPY_TAIL)
        code, out, _ = fakes.invoke(["restore", explicit])
        self.assertEqual(code, 0)
        self.assertIn(OLDER, out)
        copied = fake.joined_calls()[fake.index_of("docker cp")]
        self.assertIn(explicit, copied)
        fake.assert_done()

    def test_declined_confirm_changes_nothing(self):
        # Given the user declines the prompt
        self.confirm.return_value = False
        fake = self.use_script([COMPOSE_IMAGES, INSTANCE])
        code, out, _ = fakes.invoke(["restore"])
        # Then the command exits cleanly before any mutation
        self.assertEqual(code, 0)
        self.assertIn("Aborted", out)
        joined = " ".join(fake.joined_calls())
        self.assertNotIn(" down", joined)
        self.assertNotIn("--shm-size=1g", joined)

    def test_failed_restore_never_touches_the_live_database(self):
        fake = self.use_script(
            [COMPOSE_IMAGES, INSTANCE, STOP_PS, STOP_DOWN, CLEAR_HELPER,
             RUN_HELPER, READY, COPY_IN, DROP_INCOMING, CREATE_INCOMING,
             ("pg_restore", fakes.fail()),
             ("docker rm -f hindsight-restore", fakes.ok())])
        # When pg_restore fails mid-restore
        code, _, _ = fakes.invoke(["restore"])
        # Then the run fails, no rename or live drop was ever issued, and the
        # maintenance server is cleaned up
        self.assertNotEqual(code, 0)
        joined = " ".join(fake.joined_calls())
        self.assertNotIn("RENAME TO", joined)
        self.assertNotIn("DROP DATABASE hindsight ", joined)
        self.assertGreater(fake.index_of("docker rm -f hindsight-restore"), -1)
        fake.assert_done()

    def test_maintenance_server_not_ready_dies_with_its_logs(self):
        never_ready = [("pg_isready", fakes.fail())
                       for _ in range(restore.READY_PROBES)]
        fake = self.use_script(
            [COMPOSE_IMAGES, INSTANCE, STOP_PS, STOP_DOWN, CLEAR_HELPER,
             RUN_HELPER] + never_ready +
            [("docker logs hindsight-restore", fakes.ok("boom\n")),
             ("docker rm -f hindsight-restore", fakes.ok())])
        code, _, err = fakes.invoke(["restore"])
        self.assertEqual(code, 1)
        self.assertIn("did not come up", err)
        fake.assert_done()

    def test_no_dumps_dies(self):
        for name in (NEWEST, OLDER):
            os.remove(os.path.join(self.backup_dir, name))
        self.use_script([])
        code, _, err = fakes.invoke(["restore"])
        self.assertEqual(code, 1)
        self.assertIn("No dump found", err)



    def test_failed_swap_renames_the_live_database_back(self):
        fake = self.use_script(
            [COMPOSE_IMAGES, INSTANCE, STOP_PS, STOP_DOWN, CLEAR_HELPER,
             RUN_HELPER, READY, COPY_IN, DROP_INCOMING, CREATE_INCOMING,
             PG_RESTORE, DROP_PREVIOUS_IF, RENAME_LIVE,
             ("ALTER DATABASE hindsight_incoming RENAME TO hindsight", fakes.fail()),
             ("ALTER DATABASE hindsight_previous RENAME TO hindsight", fakes.ok()),
             REMOVE_HELPER])
        # When the swap fails after the live database was renamed away
        code, _, _ = fakes.invoke(["restore"])
        # Then the live database gets its name back and nothing is dropped
        self.assertNotEqual(code, 0)
        self.assertGreater(fake.index_of("hindsight_previous RENAME TO hindsight"),
                           fake.index_of("hindsight_incoming RENAME TO hindsight"))
        self.assertNotIn("DROP DATABASE hindsight_previous",
                         " ".join(fake.joined_calls()))
        fake.assert_done()


if __name__ == "__main__":
    unittest.main()
