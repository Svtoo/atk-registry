#!/usr/bin/env python3
"""Tests for conform.py's directive management: the shipped search directive
is installed once, kept current while ATK owns it, and never stomps a user's
own edit."""
import contextlib
import io
import os
import shutil
import tempfile
import unittest
from unittest import mock

import conform

BASE = "http://localhost:8888"
BANK = "default"
DIR_PATH = "/v1/default/banks/default/directives"
TEXT = "Search every named aspect before done()."


class FakeApi:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def __call__(self, base, method, path, body=None):
        self.calls.append((method, path, body))
        needle, response = self.script.pop(0)
        assert needle == (method, path), "expected %r, got %r" % (needle, (method, path))
        return response


class DirectiveTest(unittest.TestCase):
    def setUp(self):
        self.plugin_dir = tempfile.mkdtemp()
        with open(os.path.join(self.plugin_dir, "search-directive.md"), "w") as fh:
            fh.write(TEXT + "\n")
        patcher = mock.patch.object(conform, "PLUGIN_DIR", self.plugin_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_fresh_bank_gets_the_shipped_directive(self):
        api = FakeApi([
            (("GET", DIR_PATH), {"items": [], "total": 0}),
            (("POST", DIR_PATH), {"id": "dir-1", "name": conform.DIRECTIVE_NAME}),
        ])
        with mock.patch.object(conform, "api", api):
            # When conform runs against a bank with no directive
            conform.conform_directive(BASE, BANK, force=False)
        # Then the shipped text is created under ATK's name and recorded
        self.assertEqual(api.calls[1], ("POST", DIR_PATH,
                                        {"name": conform.DIRECTIVE_NAME, "content": TEXT}))
        self.assertEqual(conform.read_state(BANK)["directive"],
                         {"id": "dir-1", "content": TEXT})


    def test_owned_directive_follows_the_file(self):
        conform.write_state(BANK, directive={"id": "dir-1", "content": "old text"})
        api = FakeApi([
            (("GET", DIR_PATH), {"items": [{"id": "dir-1", "name": conform.DIRECTIVE_NAME,
                                             "content": "old text"}], "total": 1}),
            (("PATCH", DIR_PATH + "/dir-1"), {"id": "dir-1"}),
        ])
        with mock.patch.object(conform, "api", api):
            # When the shipped file changed and the server still holds what ATK wrote
            conform.conform_directive(BASE, BANK, force=False)
        # Then the directive is updated to the file and re-recorded
        self.assertEqual(api.calls[1], ("PATCH", DIR_PATH + "/dir-1", {"content": TEXT}))
        self.assertEqual(conform.read_state(BANK)["directive"],
                         {"id": "dir-1", "content": TEXT})


    def test_directive_edited_on_the_server_is_left_alone(self):
        conform.write_state(BANK, directive={"id": "dir-1", "content": "old text"})
        api = FakeApi([
            (("GET", DIR_PATH), {"items": [{"id": "dir-1", "name": conform.DIRECTIVE_NAME,
                                             "content": "the user's own wording"}], "total": 1}),
        ])
        out = io.StringIO()
        with mock.patch.object(conform, "api", api), contextlib.redirect_stdout(out):
            # When the server no longer holds what ATK wrote
            conform.conform_directive(BASE, BANK, force=False)
        # Then nothing is written, the record keeps ATK's last text, and the
        # user is told how to hand it back
        self.assertEqual(len(api.calls), 1)
        self.assertEqual(conform.read_state(BANK)["directive"]["content"], "old text")
        self.assertIn("search directive changed since ATK applied it", out.getvalue())
        self.assertIn("./conform.sh --force", out.getvalue())


    def test_directive_deleted_on_the_server_stays_deleted(self):
        conform.write_state(BANK, directive={"id": "dir-1", "content": TEXT})
        api = FakeApi([
            (("GET", DIR_PATH), {"items": [], "total": 0}),
        ])
        out = io.StringIO()
        with mock.patch.object(conform, "api", api), contextlib.redirect_stdout(out):
            # When the user deleted the directive ATK installed
            conform.conform_directive(BASE, BANK, force=False)
        # Then it is not reinstalled, the record stays, and the user is told
        # how to hand it back
        self.assertEqual(len(api.calls), 1)
        self.assertEqual(conform.read_state(BANK)["directive"]["content"], TEXT)
        self.assertIn("search directive removed since ATK applied it", out.getvalue())
        self.assertIn("./conform.sh --force", out.getvalue())

    def test_force_reinstalls_a_directive_the_user_deleted(self):
        conform.write_state(BANK, directive={"id": "dir-1", "content": "old text"})
        api = FakeApi([
            (("GET", DIR_PATH), {"items": [], "total": 0}),
            (("POST", DIR_PATH), {"id": "dir-2", "name": conform.DIRECTIVE_NAME}),
        ])
        with mock.patch.object(conform, "api", api):
            # When ATK is told to take the directive back
            conform.conform_directive(BASE, BANK, force=True)
        # Then the shipped text is installed again under a fresh record
        self.assertEqual(api.calls[1], ("POST", DIR_PATH,
                                        {"name": conform.DIRECTIVE_NAME, "content": TEXT}))
        self.assertEqual(conform.read_state(BANK)["directive"],
                         {"id": "dir-2", "content": TEXT})

    def test_off_retires_the_directive_atk_installed(self):
        conform.write_state(BANK, directive={"id": "dir-1", "content": TEXT})
        api = FakeApi([
            (("GET", DIR_PATH), {"items": [{"id": "dir-1", "name": conform.DIRECTIVE_NAME,
                                             "content": TEXT}], "total": 1}),
            (("DELETE", DIR_PATH + "/dir-1"), {}),
        ])
        with mock.patch.object(conform, "api", api):
            # When management is switched off while ATK still owns the directive
            conform.retire_directive(BASE, BANK)
        # Then the directive is removed and the record cleared
        self.assertEqual(api.calls[1][:2], ("DELETE", DIR_PATH + "/dir-1"))
        self.assertNotIn("directive", conform.read_state(BANK))

    def test_off_leaves_a_directive_the_user_edited(self):
        conform.write_state(BANK, directive={"id": "dir-1", "content": TEXT})
        api = FakeApi([
            (("GET", DIR_PATH), {"items": [{"id": "dir-1", "name": conform.DIRECTIVE_NAME,
                                             "content": "the user's own wording"}], "total": 1}),
        ])
        with mock.patch.object(conform, "api", api):
            # When management is switched off but the user changed the directive
            conform.retire_directive(BASE, BANK)
        # Then it stays
        self.assertEqual(len(api.calls), 1)



CFG_PATH = "/v1/default/banks/default/config"


class McpToolsTest(unittest.TestCase):
    """The env var only reaches a container ATK runs, so the bank override is
    what carries the narrowed surface to an instance someone else runs."""

    def setUp(self):
        self.plugin_dir = tempfile.mkdtemp()
        patcher = mock.patch.object(conform, "PLUGIN_DIR", self.plugin_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_bank_with_no_override_gets_the_skill_s_tools(self):
        api = FakeApi([
            (("GET", CFG_PATH), {"overrides": {}}),
            (("PATCH", CFG_PATH), {}),
        ])
        with mock.patch.object(conform, "api", api):
            conform.conform_tools(BASE, BANK, force=False)
        self.assertEqual(api.calls[1], ("PATCH", CFG_PATH,
                                        {"updates": {"mcp_enabled_tools": conform.MCP_TOOLS}}))
        self.assertEqual(conform.read_state(BANK)["tools"], conform.MCP_TOOLS)

    def test_a_list_atk_owns_follows_the_plugin(self):
        conform.write_state(BANK, tools=["recall"])
        api = FakeApi([
            (("GET", CFG_PATH), {"overrides": {"mcp_enabled_tools": ["recall"]}}),
            (("PATCH", CFG_PATH), {}),
        ])
        with mock.patch.object(conform, "api", api):
            conform.conform_tools(BASE, BANK, force=False)
        self.assertEqual(api.calls[1][2],
                         {"updates": {"mcp_enabled_tools": conform.MCP_TOOLS}})

    def test_a_list_set_outside_atk_is_left_alone(self):
        conform.write_state(BANK, tools=["recall"])
        api = FakeApi([
            (("GET", CFG_PATH), {"overrides": {"mcp_enabled_tools": ["recall", "retain"]}}),
        ])
        out = io.StringIO()
        with mock.patch.object(conform, "api", api), contextlib.redirect_stdout(out):
            conform.conform_tools(BASE, BANK, force=False)
        self.assertEqual(len(api.calls), 1)
        self.assertIn("outside ATK", out.getvalue())
        self.assertIn("./conform.sh --force", out.getvalue())

    def test_force_takes_a_list_back(self):
        conform.write_state(BANK, tools=["recall"])
        api = FakeApi([
            (("GET", CFG_PATH), {"overrides": {"mcp_enabled_tools": ["recall", "retain"]}}),
            (("PATCH", CFG_PATH), {}),
        ])
        with mock.patch.object(conform, "api", api):
            conform.conform_tools(BASE, BANK, force=True)
        self.assertEqual(api.calls[1][2],
                         {"updates": {"mcp_enabled_tools": conform.MCP_TOOLS}})

    def test_a_list_in_custom_wins_over_the_shipped_one(self):
        # Given the user lists their own tools under custom/
        os.makedirs(os.path.join(self.plugin_dir, "custom"))
        with open(os.path.join(self.plugin_dir, "custom", "mcp-tools.txt"), "w") as fh:
            fh.write("recall\nretain\n")
        api = FakeApi([
            (("GET", CFG_PATH), {"overrides": {}}),
            (("PATCH", CFG_PATH), {}),
        ])
        # When a fresh bank is conformed
        with mock.patch.object(conform, "api", api):
            conform.conform_tools(BASE, BANK, force=False)
        # Then that list, not the shipped one, is applied and recorded
        self.assertEqual(api.calls[1][2], {"updates": {"mcp_enabled_tools": ["recall", "retain"]}})
        self.assertEqual(conform.read_state(BANK)["tools"], ["recall", "retain"])

    def test_blank_lines_in_the_custom_list_are_not_tools(self):
        os.makedirs(os.path.join(self.plugin_dir, "custom"))
        with open(os.path.join(self.plugin_dir, "custom", "mcp-tools.txt"), "w") as fh:
            fh.write("recall\n\nreflect\n\n")
        api = FakeApi([
            (("GET", CFG_PATH), {"overrides": {}}),
            (("PATCH", CFG_PATH), {}),
        ])
        # When the bank is conformed
        with mock.patch.object(conform, "api", api):
            conform.conform_tools(BASE, BANK, force=False)
        # Then only the named tools are sent
        self.assertEqual(api.calls[1][2], {"updates": {"mcp_enabled_tools": ["recall", "reflect"]}})

    def test_an_empty_custom_list_stops_instead_of_guessing(self):
        os.makedirs(os.path.join(self.plugin_dir, "custom"))
        open(os.path.join(self.plugin_dir, "custom", "mcp-tools.txt"), "w").close()
        api = FakeApi([(("GET", CFG_PATH), {"overrides": {}})])
        err = io.StringIO()
        # When the bank is conformed
        with mock.patch.object(conform, "api", api), contextlib.redirect_stderr(err), \
                self.assertRaises(SystemExit):
            conform.conform_tools(BASE, BANK, force=False)
        # Then nothing is sent and the file is named
        self.assertEqual(api.calls, [])
        self.assertIn("custom/mcp-tools.txt", err.getvalue())

    def test_the_container_default_is_the_same_list(self):
        # A local container narrows its own surface from the compose file, so
        # the two copies must not drift.
        compose = os.path.join(os.path.dirname(conform.__file__), "..", "docker-compose.yml")
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "..", "docker-compose.yml")) as fh:
            line = [l for l in fh if "HINDSIGHT_API_MCP_ENABLED_TOOLS" in l][0]
        shipped = line.split('"')[1].split(",")
        self.assertEqual(shipped, conform.MCP_TOOLS)


class FreshBankTest(unittest.TestCase):
    """A bank that had to be created cannot be carrying the user's overrides,
    whatever ATK once applied to a bank of that name."""

    def setUp(self):
        self.plugin_dir = tempfile.mkdtemp()
        with open(os.path.join(self.plugin_dir, "search-directive.md"), "w") as fh:
            fh.write(TEXT + "\n")
        with open(os.path.join(self.plugin_dir, "retain-instructions.md"), "w") as fh:
            fh.write("keep the code\n")
        patcher = mock.patch.object(conform, "PLUGIN_DIR", self.plugin_dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {"HINDSIGHT_BANK": BANK,
                                           "HINDSIGHT_RETAIN_MODE": "custom"})
        env.start()
        self.addCleanup(env.stop)
        argv = mock.patch.object(conform.sys, "argv", ["conform.py"])
        argv.start()
        self.addCleanup(argv.stop)

    def test_a_recreated_bank_is_configured_rather_than_left_alone(self):
        # Given a record from the bank that used to live under this name,
        # destroyed since by an uninstall or a bank delete
        conform.write_state(BANK, applied={"retain_extraction_mode": "custom"},
                            directive={"id": "dir-1", "content": TEXT},
                            tools=list(conform.MCP_TOOLS))
        api = FakeApi([
            (("GET", "/v1/default/banks"), {"banks": []}),
            (("PUT", "/v1/default/banks/%s" % BANK), {}),
            (("GET", CFG_PATH), {"overrides": {}}),
            (("PATCH", CFG_PATH), {}),
            (("GET", CFG_PATH), {"overrides": {}}),
            (("PATCH", CFG_PATH), {}),
            (("GET", DIR_PATH), {"items": [], "total": 0}),
            (("POST", DIR_PATH), {"id": "dir-2", "name": conform.DIRECTIVE_NAME}),
        ])
        out = io.StringIO()
        with mock.patch.object(conform, "api", api), contextlib.redirect_stdout(out):
            conform.main()
        # Then the fresh bank gets ATK's settings instead of being read as an
        # override the user made
        self.assertNotIn("leaving it alone", out.getvalue())
        self.assertIn("created bank", out.getvalue())
        methods = [(m, p) for m, p, _ in api.calls]
        self.assertIn(("PATCH", CFG_PATH), methods)
        self.assertIn(("POST", DIR_PATH), methods)


class StateSurvivesUpgradeTest(unittest.TestCase):
    def setUp(self):
        self.plugin_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.plugin_dir, True)
        for name in ("plugin.yaml", "conform.sh", ".env"):
            open(os.path.join(self.plugin_dir, name), "w").close()
        patcher = mock.patch.object(conform, "PLUGIN_DIR", self.plugin_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_record_survives_an_upgrade_that_keeps_only_custom_and_env(self):
        applied = {"retain_extraction_mode": "custom"}
        conform.write_state(BANK, applied=applied)
        # When atk upgrade replaces every plugin file except custom/ and .env
        for entry in os.listdir(self.plugin_dir):
            if entry in ("custom", ".env"):
                continue
            path = os.path.join(self.plugin_dir, entry)
            shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
        # Then ATK still knows what it applied
        self.assertEqual(conform.read_state(BANK)["applied"], applied)


if __name__ == "__main__":
    unittest.main()
