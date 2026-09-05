#!/usr/bin/env python3
"""Tests for the CLI entry point: signal handling and failure diagnostics."""
import os
import signal
import tempfile
import unittest
from unittest import mock

import fakes
from hindsight_cli import shell
from test_ops import INSTANCE_JSON


class SignalHandlingTest(unittest.TestCase):
    def setUp(self):
        original = signal.getsignal(signal.SIGTERM)
        self.addCleanup(signal.signal, signal.SIGTERM, original)

    def test_sigterm_raises_systemexit_so_cleanup_runs(self):
        # Given any command has installed the handler
        fake = fakes.FakeRun([("ps", fakes.ok("hindsight\n"))])
        with mock.patch.object(shell, "run", fake):
            fakes.invoke(["service", "status"])
        handler = signal.getsignal(signal.SIGTERM)
        # When launchd or the user terminates the process
        with self.assertRaises(SystemExit) as caught:
            handler(signal.SIGTERM, None)
        # Then finally blocks run and the shell sees 128+15
        self.assertEqual(caught.exception.code, 143)

    def test_keyboard_interrupt_exits_130_without_traceback(self):
        fake = fakes.FakeRun([("ps", fakes.interrupt())])
        with mock.patch.object(shell, "run", fake):
            code, _, err = fakes.invoke(["service", "status"])
        self.assertEqual(code, 130)
        self.assertNotIn("Traceback", err)


class FailureSurfaceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env_patch = mock.patch.dict(
            os.environ, {"HINDSIGHT_BACKUP_DIR": self.tmp.name}, clear=False)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.notify = mock.Mock()
        notify_patch = mock.patch.object(shell, "notify", self.notify)
        notify_patch.start()
        self.addCleanup(notify_patch.stop)

    def test_captured_stderr_is_surfaced_on_subprocess_failure(self):
        docker_error = "Error response from daemon: no such container"
        fake = fakes.FakeRun([
            ("docker exec hindsight true", fakes.ok()),
            ("instance.json", fakes.fail(stderr=docker_error))])
        with mock.patch.object(shell, "run", fake):
            code, _, err = fakes.invoke(["backup"])
        # Then the tool's own error text and a failure line reach stderr
        self.assertNotEqual(code, 0)
        self.assertIn(docker_error, err)
        self.assertIn("❌", err)

    def test_signal_killed_subprocess_maps_to_shell_exit_code(self):
        fake = fakes.FakeRun([
            ("docker exec hindsight true", fakes.ok()),
            ("instance.json", fakes.ok(INSTANCE_JSON)),
            ("pg_dump", fakes.fail(returncode=-9))])
        with mock.patch.object(shell, "run", fake):
            code, _, _ = fakes.invoke(["backup"])
        self.assertEqual(code, 137)

    def test_missing_docker_binary_dies_cleanly(self):
        def binary_missing(cmd, kwargs):
            raise FileNotFoundError("docker")
        fake = fakes.FakeRun([("ps", binary_missing)])
        with mock.patch.object(shell, "run", fake):
            code, _, err = fakes.invoke(["service", "status"])
        self.assertEqual(code, 1)
        self.assertIn("docker", err)
        self.assertNotIn("Traceback", err)


if __name__ == "__main__":
    unittest.main()
