#!/usr/bin/env python3
"""Tests for the shared modules: configuration, endpoint resolution, the HTTP
client seam, and the pure helpers."""
import datetime
import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

import fakes
from hindsight_cli import client, config, shell

INSTANCE_JSON = """{
  "pid": 73,
  "port": 5432,
  "data_dir": "/home/hindsight/.pg0/instances/hindsight/data",
  "installation_dir": "/home/hindsight/.pg0/installation",
  "username": "hindsight",
  "password": "hindsight",
  "database": "hindsight",
  "version": "18.1.0"
}"""


class ConfigTest(unittest.TestCase):
    def test_defaults(self):
        # Given an empty environment
        cfg = config.Config({})
        # Then every setting falls back to the shipped default
        self.assertEqual(cfg.mode, "local")
        self.assertEqual(cfg.url, "http://localhost:8888")
        self.assertEqual(cfg.bank, "default")
        self.assertEqual(cfg.volume_name, "hindsight_data")
        self.assertEqual(cfg.models_volume_name, "hindsight_data_models")
        self.assertEqual(cfg.backup_dir, "")

    def test_environment_overrides(self):
        mode = "remote"
        url = "http://example:1234"
        bank = "workbank"
        volume = "othervol"
        backup_dir = "/somewhere/backups"
        # Given every setting overridden in the environment
        cfg = config.Config({
            "HINDSIGHT_MODE": mode,
            "HINDSIGHT_URL": url,
            "HINDSIGHT_BANK": bank,
            "HINDSIGHT_VOLUME_NAME": volume,
            "HINDSIGHT_BACKUP_DIR": backup_dir,
        })
        # Then the environment values win and the models volume derives
        self.assertEqual(cfg.mode, mode)
        self.assertEqual(cfg.url, url)
        self.assertEqual(cfg.bank, bank)
        self.assertEqual(cfg.volume_name, volume)
        self.assertEqual(cfg.models_volume_name, volume + "_models")
        self.assertEqual(cfg.backup_dir, backup_dir)


class ResolveEndpointsTest(unittest.TestCase):
    def test_local_ollama_defaults(self):
        # Given local mode with the ollama provider and no URLs set
        cfg = config.Config({})
        env = config.resolve_endpoints(cfg, {"HINDSIGHT_LLM_PROVIDER": "ollama"})
        # Then both endpoints point at host ollama and the embedding model
        # gets its default
        self.assertEqual(env["HINDSIGHT_LLM_BASE_URL"], config.HOST_OLLAMA)
        self.assertEqual(env["HINDSIGHT_EMBEDDING_BASE_URL"], config.HOST_OLLAMA)
        self.assertEqual(env["HINDSIGHT_EMBEDDING_MODEL"], "mxbai-embed-large")

    def test_no_provider_is_not_read_as_ollama(self):
        # Given no provider, which is a configuration error rather than a choice
        cfg = config.Config({})
        env = config.resolve_endpoints(cfg, {})
        # Then nothing points the LLM at this machine's ollama on its behalf
        self.assertNotIn("HINDSIGHT_LLM_BASE_URL", env)

    def test_cloud_provider_keeps_llm_url_unset(self):
        # Given a cloud LLM provider with no URL supplied
        cfg = config.Config({})
        env = config.resolve_endpoints(cfg, {"HINDSIGHT_LLM_PROVIDER": "groq"})
        # Then the LLM URL stays unset for the provider default, while
        # embeddings still need the host rewrite
        self.assertNotIn("HINDSIGHT_LLM_BASE_URL", env)
        self.assertEqual(env["HINDSIGHT_EMBEDDING_BASE_URL"], config.HOST_OLLAMA)

    def test_user_urls_win(self):
        llm_url = "http://my-llm:1111/v1"
        embed_url = "http://my-embed:2222/v1"
        # Given URLs the user set explicitly
        cfg = config.Config({})
        env = config.resolve_endpoints(cfg, {
            "HINDSIGHT_LLM_BASE_URL": llm_url,
            "HINDSIGHT_EMBEDDING_BASE_URL": embed_url,
        })
        # Then they are untouched
        self.assertEqual(env["HINDSIGHT_LLM_BASE_URL"], llm_url)
        self.assertEqual(env["HINDSIGHT_EMBEDDING_BASE_URL"], embed_url)

    def test_empty_environment_values_behave_as_unset(self):
        # Given variables that are set but empty, as bash ${:-} treated them
        cfg = config.Config({})
        env = config.resolve_endpoints(cfg, {
            "HINDSIGHT_LLM_PROVIDER": "",
            "HINDSIGHT_EMBEDDING_MODEL": "",
        })
        # Then the embedding default applies, and the empty provider is still
        # no provider
        self.assertNotIn("HINDSIGHT_LLM_BASE_URL", env)
        self.assertEqual(env["HINDSIGHT_EMBEDDING_MODEL"], "mxbai-embed-large")

    def test_remote_mode_only_defaults_embedding_model(self):
        # Given remote mode
        cfg = config.Config({"HINDSIGHT_MODE": "remote"})
        env = config.resolve_endpoints(cfg, {})
        # Then no endpoint rewrite happens; only the embedding model default
        self.assertNotIn("HINDSIGHT_LLM_BASE_URL", env)
        self.assertNotIn("HINDSIGHT_EMBEDDING_BASE_URL", env)
        self.assertEqual(env["HINDSIGHT_EMBEDDING_MODEL"], "mxbai-embed-large")


class IsLocalOllamaTest(unittest.TestCase):
    def test_matches_the_three_local_hosts(self):
        for url in ("http://localhost:11434/v1",
                    "http://127.0.0.1:11434/v1",
                    "http://host.docker.internal:11434/v1"):
            self.assertTrue(config.is_local_ollama(url))

    def test_rejects_other_endpoints(self):
        for url in ("https://api.groq.com/openai/v1", "", None):
            self.assertFalse(config.is_local_ollama(url))


class ComposeCmdTest(unittest.TestCase):
    def test_base_compose_file_only(self):
        # Given a plugin dir without a custom override
        with tempfile.TemporaryDirectory() as plugin_dir:
            cfg = config.Config({}, plugin_dir=plugin_dir)
            cmd = shell.compose_cmd(cfg)
        # Then compose runs on the shipped file alone
        self.assertEqual(
            cmd, ["docker", "compose", "-f",
                  os.path.join(plugin_dir, "docker-compose.yml")])

    def test_custom_override_is_added(self):
        # Given a custom/docker-compose.override.yml
        with tempfile.TemporaryDirectory() as plugin_dir:
            override = os.path.join(plugin_dir, "custom",
                                    "docker-compose.override.yml")
            os.makedirs(os.path.dirname(override))
            with open(override, "w") as fh:
                fh.write("services: {}\n")
            cfg = config.Config({}, plugin_dir=plugin_dir)
            cmd = shell.compose_cmd(cfg)
        # Then both files are passed in shipped-then-override order
        self.assertEqual(
            cmd, ["docker", "compose",
                  "-f", os.path.join(plugin_dir, "docker-compose.yml"),
                  "-f", override])


class PgInstanceTest(unittest.TestCase):
    def test_parses_connection_details(self):
        # Given the instance file pg0 writes
        pg = shell.PgInstance(INSTANCE_JSON)
        # Then every connection detail is derived from it
        self.assertEqual(pg.bin_dir, "/home/hindsight/.pg0/installation/18.1.0/bin")
        self.assertEqual(pg.lib_dir, "/home/hindsight/.pg0/installation/18.1.0/lib")
        self.assertEqual(pg.data_dir, "/home/hindsight/.pg0/instances/hindsight/data")
        self.assertEqual(pg.port, "5432")
        self.assertEqual(pg.user, "hindsight")
        self.assertEqual(pg.password, "hindsight")
        self.assertEqual(pg.database, "hindsight")


class PruneSelectionTest(unittest.TestCase):
    def test_keeps_three_days_two_weeks_two_months(self):
        # Given dumps spanning same-day duplicates, dense recent days, and
        # older weekly/monthly stragglers
        names = ["hindsight_backup_%s.dump" % stamp for stamp in (
            "2026-08-21_0900", "2026-08-21_1800", "2026-08-20_0900",
            "2026-08-19_0900", "2026-08-18_0900", "2026-08-17_0900",
            "2026-08-16_0900", "2026-08-15_0900", "2026-08-14_0900",
            "2026-08-13_0900", "2026-08-03_0900", "2026-07-28_0900",
            "2026-07-10_0900", "2026-06-05_0900", "2026-05-01_0900")]
        # When the retention selection runs
        deletions = shell.prune_selection(names)
        # Then five survive: the newest of each of three days, of the week
        # before, and of the month before
        self.assertEqual(sorted(set(names) - set(deletions)), [
            "hindsight_backup_2026-07-28_0900.dump",
            "hindsight_backup_2026-08-16_0900.dump",
            "hindsight_backup_2026-08-19_0900.dump",
            "hindsight_backup_2026-08-20_0900.dump",
            "hindsight_backup_2026-08-21_1800.dump",
        ])
        self.assertEqual(len(deletions), 10)

    def test_a_name_carrying_an_impossible_date_is_left_alone(self):
        # Given a file named like a dump whose date does not exist
        deletions = shell.prune_selection([
            "hindsight_backup_2026-02-30_1200.dump",
            "hindsight_backup_2026-08-21_0900.dump"])
        # Then the selection neither crashes nor claims it
        self.assertEqual(deletions, [])

    def test_a_versioned_dump_rotates_beside_an_unversioned_one(self):
        # Given yesterday's dump from before versions were in the name and
        # two of today's carrying it
        older = "hindsight_backup_2026-08-20_0900.dump"
        morning = "hindsight_backup_2026-08-21_0900_hs0.9.2.dump"
        evening = "hindsight_backup_2026-08-21_1800_hs0.9.3.dump"
        # When the selection runs
        deletions = shell.prune_selection([older, morning, evening])
        # Then the day keeps only its newest, and the old name still rotates
        self.assertEqual(deletions, [morning])

    def test_ignores_foreign_files(self):
        # Given a file that does not match the dump naming scheme
        deletions = shell.prune_selection(["hindsight_backup_notadate.dump",
                                         "hindsight_backup_2026-08-21_0900.dump"])
        # Then it is neither kept nor deleted by the selection
        self.assertEqual(deletions, [])


class DumpDirectoryTest(unittest.TestCase):
    def test_newest_dump_picks_latest_by_name(self):
        older = "hindsight_backup_2026-08-20_0900.dump"
        newer = "hindsight_backup_2026-08-21_0900.dump"
        with tempfile.TemporaryDirectory() as backup_dir:
            for name in (newer, older):
                open(os.path.join(backup_dir, name), "w").close()
            cfg = config.Config({"HINDSIGHT_BACKUP_DIR": backup_dir})
            # When the newest dump is looked up
            found = shell.newest_dump(cfg)
        # Then the lexicographically newest dated file wins
        self.assertEqual(found, os.path.join(backup_dir, newer))

    def test_dump_discovery_survives_glob_metacharacters_in_the_path(self):
        name = "hindsight_backup_2026-08-21_0900.dump"
        with tempfile.TemporaryDirectory() as parent:
            backup_dir = os.path.join(parent, "Backups [Mac]")
            os.mkdir(backup_dir)
            open(os.path.join(backup_dir, name), "w").close()
            cfg = config.Config({"HINDSIGHT_BACKUP_DIR": backup_dir})
            self.assertEqual(shell.newest_dump(cfg),
                             os.path.join(backup_dir, name))

    def test_freshness_skips_files_pruned_mid_check(self):
        name = "hindsight_backup_2026-08-21_0900.dump"
        with tempfile.TemporaryDirectory() as backup_dir:
            open(os.path.join(backup_dir, name), "w").close()
            cfg = config.Config({"HINDSIGHT_BACKUP_DIR": backup_dir})
            # Given a dump pruned between discovery and the mtime check
            with mock.patch("os.path.getmtime", side_effect=FileNotFoundError):
                self.assertFalse(shell.dumps_are_fresh(cfg))

    def test_newest_dump_is_none_when_empty(self):
        with tempfile.TemporaryDirectory() as backup_dir:
            cfg = config.Config({"HINDSIGHT_BACKUP_DIR": backup_dir})
            self.assertIsNone(shell.newest_dump(cfg))

    def test_freshness_is_a_day_by_mtime(self):
        name = "hindsight_backup_2026-08-21_0900.dump"
        at = datetime.datetime(2026, 8, 22, 12, 0, 0)
        with tempfile.TemporaryDirectory() as backup_dir:
            path = os.path.join(backup_dir, name)
            open(path, "w").close()
            cfg = config.Config({"HINDSIGHT_BACKUP_DIR": backup_dir})
            # Given a dump written two hours before the check
            fresh_mtime = (at - datetime.timedelta(hours=2)).timestamp()
            os.utime(path, (fresh_mtime, fresh_mtime))
            self.assertTrue(shell.dumps_are_fresh(cfg, at=at))
            # Given the same dump aged past a day
            stale_mtime = (at - datetime.timedelta(hours=25)).timestamp()
            os.utime(path, (stale_mtime, stale_mtime))
            self.assertFalse(shell.dumps_are_fresh(cfg, at=at))


class RenderPlistTest(unittest.TestCase):
    def test_renders_the_launchd_job(self):
        label = "com.atk.hindsight-backup"
        plugin_dir = "/plugins/hindsight"
        log_path = "/logs/atk-hindsight-backup.log"
        expected = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
    <key>Label</key><string>%s</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>%s/backup.sh</string>
        <string>--if-stale</string>
    </array>
    <key>StartInterval</key><integer>3600</integer>
    <key>RunAtLoad</key><true/>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
    <key>StandardOutPath</key><string>%s</string>
    <key>StandardErrorPath</key><string>%s</string>
</dict></plist>
""" % (label, plugin_dir, log_path, log_path)
        self.assertEqual(shell.render_plist(label, plugin_dir, log_path), expected)


class ConfirmTest(unittest.TestCase):
    def test_declines_without_a_terminal(self):
        out = io.StringIO()
        with mock.patch.object(shell.sys.stdin, "isatty", return_value=False), \
                redirect_stdout(out):
            answer = shell.confirm("Proceed?")
        self.assertFalse(answer)
        self.assertIn("no terminal", out.getvalue())

    def test_interactive_replies(self):
        with mock.patch.object(shell.sys.stdin, "isatty", return_value=True):
            for reply in ("y", "Y", "yes", "YES", "Yes"):
                with mock.patch("builtins.input", return_value=reply):
                    self.assertTrue(shell.confirm("Proceed?"))
            for reply in ("", "n", "nope", "si"):
                with mock.patch("builtins.input", return_value=reply):
                    self.assertFalse(shell.confirm("Proceed?"))

    def test_eof_at_the_prompt_declines(self):
        with mock.patch.object(shell.sys.stdin, "isatty", return_value=True), \
                mock.patch("builtins.input", side_effect=EOFError):
            self.assertFalse(shell.confirm("Proceed?"))


class WaitHealthyTest(unittest.TestCase):
    def test_retries_ninety_times_two_seconds_apart(self):
        http = mock.Mock(side_effect=OSError("down"))
        sleeps = []
        with mock.patch.object(client, "http", http), \
                mock.patch.object(shell, "sleep", sleeps.append):
            healthy = shell.wait_healthy(config.Config({}))
        self.assertFalse(healthy)
        self.assertEqual(http.call_count, 90)
        self.assertEqual(sleeps, [2] * 90)


class HumanSizeTest(unittest.TestCase):
    def test_reports_bytes_kilo_mega_giga(self):
        cases = ((512, "512B"), (4 * 1024, "4K"),
                 (113 * 1024 * 1024, "113M"), (2 * 1024 ** 3, "2G"))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sized")
            for size, expected in cases:
                with open(path, "wb") as fh:
                    fh.truncate(size)
                self.assertEqual(shell.human_size(path), expected)


class NotifyTest(unittest.TestCase):
    def test_builds_the_osascript_invocation(self):
        title = "Hindsight backup FAILED"
        text = "Check the log"
        with mock.patch.object(shell.subprocess, "run") as sub:
            shell.notify(title, text)
        argv = sub.call_args[0][0]
        self.assertEqual(argv[:2], ["osascript", "-e"])
        self.assertIn(title, argv[2])
        self.assertIn(text, argv[2])


class RequireBackupDirTest(unittest.TestCase):
    def test_missing_directory_dies(self):
        cfg = config.Config({"HINDSIGHT_BACKUP_DIR": "/nonexistent/backups"})
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            shell.require_backup_dir(cfg)

    def test_relative_directory_dies(self):
        with tempfile.TemporaryDirectory() as tmp:
            relative = os.path.relpath(tmp)
            cfg = config.Config({"HINDSIGHT_BACKUP_DIR": relative})
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                shell.require_backup_dir(cfg)


class McpStatefulTest(unittest.TestCase):
    def test_defaults_to_stateless_even_for_empty_values(self):
        self.assertFalse(shell.mcp_is_stateful({}))
        self.assertFalse(shell.mcp_is_stateful({"HINDSIGHT_MCP_STATELESS": ""}))
        self.assertTrue(shell.mcp_is_stateful({"HINDSIGHT_MCP_STATELESS": "false"}))


class ComposeEnvTest(unittest.TestCase):
    def test_compose_runs_with_resolved_endpoints(self):
        fake = fakes.FakeRun([("config", fakes.ok("img\n"))])
        with tempfile.TemporaryDirectory() as plugin_dir, \
                mock.patch.dict(os.environ, {"HINDSIGHT_LLM_PROVIDER": "ollama"}), \
                mock.patch.object(shell, "run", fake):
            cfg = config.Config({}, plugin_dir=plugin_dir)
            shell.compose(cfg, "config", "--images",
                        capture_output=True, text=True)
        env = fake.call_kwargs[0]["env"]
        self.assertEqual(env["HINDSIGHT_LLM_BASE_URL"], config.HOST_OLLAMA)
        self.assertEqual(env["HINDSIGHT_EMBEDDING_BASE_URL"], config.HOST_OLLAMA)


class DieTest(unittest.TestCase):
    def test_exits_one_with_message_and_hint(self):
        message = "Something broke."
        hint = "Try again."
        err = io.StringIO()
        # When die is called
        with redirect_stderr(err), self.assertRaises(SystemExit) as caught:
            shell.die(message, hint)
        # Then it exits 1 and prints the message and hint to stderr
        self.assertEqual(caught.exception.code, 1)
        self.assertEqual(err.getvalue(), "  ❌ %s\n  %s\n" % (message, hint))



class ModeAndUrlTest(unittest.TestCase):
    def test_mode_is_case_and_whitespace_insensitive(self):
        cfg = config.Config({"HINDSIGHT_MODE": " Remote "})
        self.assertEqual(cfg.mode, "remote")

    def test_unknown_mode_dies_naming_the_value(self):
        err = io.StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as raised:
            config.Config({"HINDSIGHT_MODE": "sideways"})
        self.assertEqual(raised.exception.code, 1)
        self.assertIn("HINDSIGHT_MODE 'sideways'", err.getvalue())
        self.assertIn("atk setup hindsight", err.getvalue())

    def test_url_trailing_slashes_are_stripped(self):
        # Given a URL pasted the way people write them
        cfg = config.Config({"HINDSIGHT_URL": "http://memory.example:8888//"})
        # Then every request the plugin makes has one slash
        self.assertEqual(cfg.url, "http://memory.example:8888")


if __name__ == "__main__":
    unittest.main()
