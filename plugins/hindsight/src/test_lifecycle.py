#!/usr/bin/env python3
"""Tests for the service, install and uninstall commands."""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import fakes
from hindsight_cli import client, config, shell

ID_STABLE = [("docker inspect", fakes.ok("cid-1\n")),
             ("up -d", fakes.ok()),
             ("docker inspect", fakes.ok("cid-1\n"))]
CONFORM_OK = ("conform.py", fakes.ok())
LLM_MODEL = "ornith"
OLLAMA_TAGS = json.dumps({"models": [
    {"name": LLM_MODEL + ":latest"}, {"name": "mxbai-embed-large:latest"}]})


class LifecycleCase(unittest.TestCase):
    def setUp(self):
        self.http = mock.Mock(return_value="ok")
        self.confirm = mock.Mock(return_value=True)
        self.which = mock.Mock(return_value="/usr/local/bin/tool")
        patches = ((client, "http", self.http), (shell, "confirm", self.confirm),
                   (shell, "which", self.which),
                   (shell, "sleep", lambda seconds: None))
        for module, name, value in patches:
            patcher = mock.patch.object(module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def use_env(self, env):
        patcher = mock.patch.dict(os.environ, env, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def use_script(self, script):
        fake = fakes.FakeRun(script)
        patcher = mock.patch.object(shell, "run", fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake


class ServiceTest(LifecycleCase):
    def test_status_local_healthy_exits_zero_after_probing_health(self):
        self.use_script([("ps", fakes.ok("hindsight\n"))])
        code, _, _ = fakes.invoke(["service", "status"])
        # Then the container being up is not taken as proof on its own
        self.assertEqual(code, 0)
        self.http.assert_called_once()

    def test_status_local_running_but_api_down_exits_nonzero(self):
        # Given a container that is up while the API is wedged
        self.http.side_effect = OSError("connection refused")
        self.use_script([("ps", fakes.ok("hindsight\n"))])
        code, _, err = fakes.invoke(["service", "status"])
        # Then status reports the service as unusable and says why
        self.assertNotEqual(code, 0)
        self.assertIn("is not answering", err)

    def test_status_local_probes_the_configured_url(self):
        self.use_env({"HINDSIGHT_URL": "http://memory.example:9000"})
        self.use_script([("ps", fakes.ok("hindsight\n"))])
        code, _, _ = fakes.invoke(["service", "status"])
        self.assertEqual(code, 0)
        self.assertEqual(self.http.call_args[0][1],
                         "http://memory.example:9000/health")

    def test_status_local_stopped_says_the_container_is_not_running(self):
        self.use_script([("ps", fakes.ok(""))])
        code, _, err = fakes.invoke(["service", "status"])
        self.assertNotEqual(code, 0)
        self.assertIn("container is not running", err)

    def test_status_remote_checks_health(self):
        self.use_env({"HINDSIGHT_MODE": "remote"})
        self.use_script([])
        code, _, _ = fakes.invoke(["service", "status"])
        self.assertEqual(code, 0)
        self.http.side_effect = OSError("down")
        code, _, err = fakes.invoke(["service", "status"])
        # Then an unreachable instance is named, not just a bare exit code
        self.assertNotEqual(code, 0)
        self.assertIn("Cannot reach", err)

    def test_start_local_conforms_once_healthy(self):
        fake = self.use_script(ID_STABLE + [CONFORM_OK])
        code, _, err = fakes.invoke(["service", "start"])
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        # And conform runs in the project's uv environment
        self.assertEqual(fake.call_at("conform.py"), [
            "uv", "run", "--project", config.SRC_DIR, "python",
            os.path.join(config.SRC_DIR, "conform.py")])
        fake.assert_done()

    def test_start_local_warns_when_conform_fails(self):
        # Given a bank that cannot be conformed right now
        self.use_script(ID_STABLE + [("conform.py", fakes.fail())])
        code, _, err = fakes.invoke(["service", "start"])
        # Then the service still comes up but the user hears about it
        self.assertEqual(code, 0)
        self.assertIn("retain config", err)

    def test_start_local_unhealthy_fails_and_skips_conform(self):
        # Given an API that never answers within the window
        self.http.side_effect = OSError("not up yet")
        fake = self.use_script(ID_STABLE)
        code, _, err = fakes.invoke(["service", "start"])
        # Then the start is reported as failed, not as a warning on a zero exit
        self.assertNotEqual(code, 0)
        self.assertIn("did not become healthy", err)
        fake.assert_done()

    def test_start_remote_unreachable_fails(self):
        self.use_env({"HINDSIGHT_MODE": "remote"})
        self.http.side_effect = OSError("down")
        self.use_script([])
        code, _, _ = fakes.invoke(["service", "start"])
        self.assertNotEqual(code, 0)

    def test_stop_local_runs_exactly_compose_down(self):
        fake = self.use_script([(" down", fakes.ok())])
        code, _, _ = fakes.invoke(["service", "stop"])
        self.assertEqual(code, 0)
        base_compose = shell.compose_cmd(config.Config({}, plugin_dir=config.PLUGIN_DIR))
        self.assertEqual(fake.calls[0], base_compose + ["down"])
        fake.assert_done()

    def test_logs_local_streams_compose_logs(self):
        fake = self.use_script([("logs -f", fakes.ok())])
        code, _, _ = fakes.invoke(["service", "logs"])
        self.assertEqual(code, 0)
        fake.assert_done()

    def test_stop_is_a_noop_in_remote_mode(self):
        self.use_env({"HINDSIGHT_MODE": "remote"})
        fake = self.use_script([])
        code, _, _ = fakes.invoke(["service", "stop"])
        self.assertEqual(code, 0)
        self.assertEqual(fake.calls, [])

    def test_logs_remote_refuses(self):
        self.use_env({"HINDSIGHT_MODE": "remote"})
        self.use_script([])
        code, _, _ = fakes.invoke(["service", "logs"])
        self.assertEqual(code, 1)

    def test_unknown_verb_exits_two(self):
        self.use_script([])
        code, _, _ = fakes.invoke(["service", "sideways"])
        self.assertEqual(code, 2)

    def test_recreated_stateful_container_warns_to_reconnect(self):
        # Given a start that recreates the container under stateful MCP
        self.use_env({"HINDSIGHT_MCP_STATELESS": "false"})
        self.use_script([("docker inspect", fakes.ok("cid-1\n")),
                         ("up -d", fakes.ok()),
                         ("docker inspect", fakes.ok("cid-2\n")),
                         CONFORM_OK])
        code, out, _ = fakes.invoke(["service", "start"])
        self.assertEqual(code, 0)
        self.assertIn("NEW container", out)

    def test_recreated_stateless_container_stays_quiet(self):
        self.use_script([("docker inspect", fakes.ok("cid-1\n")),
                         ("up -d", fakes.ok()),
                         ("docker inspect", fakes.ok("cid-2\n")),
                         CONFORM_OK])
        code, out, _ = fakes.invoke(["service", "start"])
        self.assertEqual(code, 0)
        self.assertNotIn("NEW container", out)


class EnvRepairTest(LifecycleCase):
    def setUp(self):
        super().setUp()
        self.plugin_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.plugin_dir, True)
        patcher = mock.patch.object(config, "PLUGIN_DIR", self.plugin_dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.env_path = os.path.join(self.plugin_dir, ".env")

    def write_env(self, body):
        with open(self.env_path, "w") as fh:
            fh.write(body)

    def read_env(self):
        with open(self.env_path) as fh:
            return fh.read()

    def test_install_strips_the_trailing_slash_atk_would_carry_into_mcp(self):
        # Given a URL pasted with the slash people write, quoted as atk writes it
        self.write_env('# Hindsight API base URL\n'
                       'HINDSIGHT_URL="http://memory.example:8888/"\n'
                       'HINDSIGHT_BANK=default\n')
        self.use_env({"HINDSIGHT_MODE": "remote",
                      "HINDSIGHT_URL": "http://memory.example:8888/"})
        self.use_script([CONFORM_OK])
        # When install runs
        code, out, _ = fakes.invoke(["install"])
        # Then atk reads a URL whose MCP endpoint resolves, and the rest of the
        # file is untouched
        self.assertEqual(code, 0)
        self.assertEqual(self.read_env(),
                         '# Hindsight API base URL\n'
                         'HINDSIGHT_URL="http://memory.example:8888"\n'
                         'HINDSIGHT_BANK=default\n')
        self.assertIn("trailing slash", out)

    def test_install_leaves_a_clean_env_file_alone(self):
        clean = 'HINDSIGHT_URL=http://memory.example:8888\nHINDSIGHT_BANK=default\n'
        self.write_env(clean)
        self.use_env({"HINDSIGHT_MODE": "remote",
                      "HINDSIGHT_URL": "http://memory.example:8888"})
        self.use_script([CONFORM_OK])
        code, out, _ = fakes.invoke(["install"])
        self.assertEqual(code, 0)
        self.assertEqual(self.read_env(), clean)
        self.assertNotIn("trailing slash", out)


SUPPORTED = json.dumps({"features": {"bank_llm_health": True}})


def probe(*statuses):
    return json.dumps({"bank_id": "default", "operations": [
        {"operation": "retain", "ok": s == "connected", "status": s}
        for s in statuses]})


class LlmCheckTest(LifecycleCase):
    """The server probes its own LLM; the plugin never sees a key or endpoint."""

    def setUp(self):
        super().setUp()
        self.use_env({"HINDSIGHT_MODE": "remote"})

    def install_with(self, *responses):
        self.http.side_effect = list(responses)
        self.use_script([CONFORM_OK])
        return fakes.invoke(["install"])

    def test_a_rejected_key_is_reported_without_failing_the_install(self):
        # Given a server whose provider rejects the configured key
        code, out, err = self.install_with("ok", SUPPORTED, probe("auth_failed"))
        # Then the user is told, and the install still stands: a failed install
        # makes atk add delete the plugin it just added
        self.assertEqual(code, 0)
        self.assertIn("rejected the API key", err)
        self.assertIn("atk setup hindsight", err)
        self.assertIn("✅ Installed", out)

    def test_a_working_llm_is_confirmed(self):
        code, out, err = self.install_with("ok", SUPPORTED, probe("connected"))
        self.assertEqual(code, 0)
        self.assertIn("LLM answered", out)
        self.assertNotIn("⚠", err)

    def test_the_probe_asks_the_configured_bank_and_sends_no_secret(self):
        self.use_env({"HINDSIGHT_BANK": "notes"})
        self.install_with("ok", SUPPORTED, probe("connected"))
        method, url, body = self.http.call_args[0][0], self.http.call_args[0][1], None
        self.assertEqual((method, url),
                         ("POST", "http://localhost:8888/v1/default/banks/notes/health/llm"))

    def test_an_instance_without_the_probe_says_the_key_is_unverified(self):
        # Given an instance where the feature is off or too old
        code, _, err = self.install_with(
            "ok", json.dumps({"features": {"bank_llm_health": False}}))
        self.assertEqual(code, 0)
        self.assertIn("unverified", err)

    def test_a_probe_that_cannot_be_reached_says_the_key_is_unverified(self):
        code, _, err = self.install_with("ok", SUPPORTED, OSError("boom"))
        self.assertEqual(code, 0)
        self.assertIn("unverified", err)


class InstallTest(LifecycleCase):
    def setUp(self):
        super().setUp()
        self.use_env({"HINDSIGHT_LLM_PROVIDER": "ollama",
                      "HINDSIGHT_LLM_MODEL": LLM_MODEL})

    def test_remote_install_checks_health_then_conforms(self):
        self.use_env({"HINDSIGHT_MODE": "remote"})
        fake = self.use_script([CONFORM_OK])
        # When a remote install runs
        code, out, _ = fakes.invoke(["install"])
        # Then the only work is the health check and the bank settings
        self.assertEqual(code, 0)
        self.assertIn("remote", out)
        self.assertIn("conform.py", fake.joined_calls()[0])
        fake.assert_done()

    def test_missing_provider_fails_with_its_own_message(self):
        # Given a local install with no provider chosen
        self.use_env({"HINDSIGHT_LLM_PROVIDER": ""})
        self.use_script([])
        code, _, err = fakes.invoke(["install"])
        # Then it says which setting is missing, not which model is absent
        self.assertEqual(code, 1)
        self.assertIn("HINDSIGHT_LLM_PROVIDER is not set", err)

    def test_missing_model_fails(self):
        self.use_env({"HINDSIGHT_LLM_MODEL": ""})
        self.use_script([])
        code, _, err = fakes.invoke(["install"])
        self.assertEqual(code, 1)
        self.assertIn("HINDSIGHT_LLM_MODEL is not set", err)

    def test_install_does_not_need_node(self):
        # Given a machine with Docker and Ollama but no Node
        self.which.side_effect = lambda name: (
            None if name == "npx" else "/usr/local/bin/" + name)
        self.http.side_effect = [OLLAMA_TAGS, "ok", "ok"]
        fake = self.use_script([
            ("docker info", fakes.ok()),
            ("curlimages", fakes.ok()),
            ("pull", fakes.ok()),
            ("up -d", fakes.ok()),
            CONFORM_OK,
        ])
        # When it installs
        code, out, _ = fakes.invoke(["install"])
        # Then the install completes
        self.assertEqual(code, 0)
        self.assertIn("✅ Installed", out)
        fake.assert_done()

    def test_untagged_model_resolves_to_latest(self):
        # Given ollama holds ornith:latest and the config names bare 'ornith'
        self.http.side_effect = [OLLAMA_TAGS, "ok", "ok"]
        fake = self.use_script([
            ("docker info", fakes.ok()),
            ("curlimages", fakes.ok()),
            ("pull", fakes.ok()),
            ("up -d", fakes.ok()),
            CONFORM_OK,
        ])
        code, out, _ = fakes.invoke(["install"])
        # Then the model check passes, the bank is conformed once the server
        # is up, and install completes
        self.assertEqual(code, 0)
        self.assertIn("Model '%s' available" % LLM_MODEL, out)
        self.assertGreater(fake.index_of("conform.py"), fake.index_of("up -d"))
        self.assertIn("✅ Installed", out)
        fake.assert_done()

    def test_ollama_not_responding_fails(self):
        self.http.side_effect = OSError("connection refused")
        self.use_script([("docker info", fakes.ok())])
        code, _, err = fakes.invoke(["install"])
        self.assertEqual(code, 1)
        self.assertIn("Ollama is not responding", err)

    def test_api_never_healthy_after_start_fails(self):
        # Given a container that starts but whose API never answers
        self.http.side_effect = [OLLAMA_TAGS] + [OSError("down")] * 200
        self.use_script([
            ("docker info", fakes.ok()),
            ("curlimages", fakes.ok()),
            ("pull", fakes.ok()),
            ("up -d", fakes.ok()),
        ])
        code, _, err = fakes.invoke(["install"])
        self.assertEqual(code, 1)
        self.assertIn("did not become healthy", err)

    def test_model_not_in_ollama_fails_listing_available(self):
        self.use_env({"HINDSIGHT_LLM_MODEL": "absent-model"})
        self.http.side_effect = [OLLAMA_TAGS]
        self.use_script([("docker info", fakes.ok())])
        code, _, err = fakes.invoke(["install"])
        self.assertEqual(code, 1)
        self.assertIn("absent-model:latest", err)
        self.assertIn("ornith:latest", err)

    def test_container_unable_to_reach_ollama_fails(self):
        self.http.side_effect = [OLLAMA_TAGS]
        self.use_script([("docker info", fakes.ok()),
                         ("curlimages", fakes.fail())])
        code, _, err = fakes.invoke(["install"])
        self.assertEqual(code, 1)
        self.assertIn("OLLAMA_HOST", err)


class UninstallTest(LifecycleCase):
    def test_remote_uninstall_touches_nothing(self):
        self.use_env({"HINDSIGHT_MODE": "remote"})
        fake = self.use_script([])
        code, out, _ = fakes.invoke(["uninstall"])
        self.assertEqual(code, 0)
        self.assertIn("untouched", out)
        self.assertEqual(fake.calls, [])

    def test_declined_confirm_keeps_the_memories_volume(self):
        self.confirm.return_value = False
        fake = self.use_script([
            ("down --rmi all", fakes.ok()),
            ("volume rm hindsight_data_models", fakes.ok()),
            ("volume inspect hindsight_data", fakes.ok()),
        ])
        code, out, _ = fakes.invoke(["uninstall"])
        self.assertEqual(code, 0)
        self.assertIn("Memories kept", out)
        self.assertNotIn(["docker", "volume", "rm", "hindsight_data"],
                         fake.calls)
        fake.assert_done()

    def test_confirmed_delete_removes_the_memories_volume(self):
        fake = self.use_script([
            ("down --rmi all", fakes.ok()),
            ("volume rm hindsight_data_models", fakes.ok()),
            ("volume inspect hindsight_data", fakes.ok()),
            ("volume rm hindsight_data", fakes.ok()),
        ])
        code, out, _ = fakes.invoke(["uninstall"])
        self.assertEqual(code, 0)
        self.assertIn("Memories deleted", out)
        fake.assert_done()

    def test_missing_volume_asks_nothing(self):
        self.use_script([
            ("down --rmi all", fakes.ok()),
            ("volume rm hindsight_data_models", fakes.ok()),
            ("volume inspect hindsight_data", fakes.fail()),
        ])
        code, _, _ = fakes.invoke(["uninstall"])
        self.assertEqual(code, 0)
        self.confirm.assert_not_called()


if __name__ == "__main__":
    unittest.main()
