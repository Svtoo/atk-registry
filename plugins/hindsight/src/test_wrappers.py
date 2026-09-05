#!/usr/bin/env python3
"""Tests for the wrapper chain: each .sh loads .env and dispatches to the
hindsight-cli entry point. Only argument-error paths are exercised, so nothing
touches docker or the API."""
import os
import subprocess
import unittest

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_wrapper(script, *args):
    return subprocess.run(
        ["bash", os.path.join(PLUGIN_DIR, script)] + list(args),
        capture_output=True, text=True)


class WrapperDispatchTest(unittest.TestCase):
    def test_a_machine_without_uv_is_told_so_instead_of_exit_127(self):
        # Given a PATH with no uv on it
        bare = {"PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", "/")}
        # When any wrapper runs
        result = subprocess.run(["bash", os.path.join(PLUGIN_DIR, "install.sh")],
                                capture_output=True, text=True, env=bare)
        # Then it stops with the missing tool named, not a bare command-not-found
        self.assertEqual(result.returncode, 1)
        self.assertIn("uv is not on PATH", result.stderr)


    def test_backup_wrapper_reaches_the_cli_argument_check(self):
        result = run_wrapper("backup.sh", "--frobnicate")
        self.assertEqual(result.returncode, 2)
        self.assertIn("No such option '--frobnicate'", result.stderr)

    def test_service_wrapper_reaches_the_cli_verb_check(self):
        result = run_wrapper("service.sh", "sideways")
        self.assertEqual(result.returncode, 2)
        self.assertIn("usage: service", result.stderr)

    def test_schedule_wrapper_reaches_the_cli_verb_check(self):
        result = run_wrapper("schedule.sh", "sideways")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Unknown argument", result.stderr)

    def test_conform_wrapper_reaches_the_script_argument_check(self):
        result = run_wrapper("conform.sh", "--frobnicate")
        self.assertEqual(result.returncode, 1)
        self.assertIn("unknown argument '--frobnicate'", result.stderr)

    def test_banks_wrapper_reaches_the_cli_verb_check(self):
        result = run_wrapper("banks.sh", "bogus")
        self.assertEqual(result.returncode, 1)
        self.assertIn("usage: banks", result.stderr)


if __name__ == "__main__":
    unittest.main()
