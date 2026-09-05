"""The service, install and uninstall commands."""
import json
import os
import sys
import urllib.error

from . import client, config, shell


def conform_bank():
    conform = os.path.join(config.SRC_DIR, "conform.py")
    result = shell.run(["uv", "run", "--project", config.SRC_DIR, "python", conform],
                       check=False)
    if result.returncode != 0:
        print("  ⚠  Could not check the bank's retain config. Run ./conform.sh once",
              file=sys.stderr)
        print("     the server is reachable.", file=sys.stderr)


# What the server reports back; it answers with a status and never with the
# provider, the model, the endpoint or the key.
LLM_DIAGNOSIS = {
    "auth_failed": "The provider rejected the API key, so nothing will be stored.",
    "not_configured": "Hindsight has no LLM configured, so nothing will be stored.",
    "unreachable": "Hindsight cannot reach the LLM.",
    "timeout": "The LLM did not answer in time.",
}


def unverified(reason):
    print("  ⚠  %s, so the LLM is unverified." % reason, file=sys.stderr)
    print("     A wrong key surfaces as memories that are never stored.",
          file=sys.stderr)


def check_llm(cfg):
    """Has the server probe the LLM its bank would use. Only the server knows
    every provider's credential shape, so this is the one check that holds for
    all of them."""
    try:
        features = json.loads(
            client.http("GET", cfg.url + "/version", timeout=10)).get("features")
    except (urllib.error.URLError, ValueError, OSError):
        features = None
    if not (features or {}).get("bank_llm_health"):
        unverified("This instance cannot test its own LLM")
        return
    try:
        report = json.loads(client.http(
            "POST", "%s/v1/default/banks/%s/health/llm" % (cfg.url, cfg.bank),
            timeout=180, body=""))
    except (urllib.error.URLError, ValueError, OSError):
        unverified("The test did not complete")
        return
    failed = [op.get("status") for op in report.get("operations") or []
              if op.get("status") != "connected"]
    if not failed:
        print("  ✓ LLM answered")
        return
    print("  ⚠  %s" % LLM_DIAGNOSIS.get(
        failed[0], "The LLM test came back '%s'." % failed[0]), file=sys.stderr)
    print("     Fix it: atk setup hindsight, then: atk install hindsight",
          file=sys.stderr)


def service(cfg, verb):
    if verb == "start":
        if cfg.mode == "remote":
            if not shell.api_healthy(cfg):
                print("Cannot reach %s" % cfg.url, file=sys.stderr)
                return 1
            print("Using remote Hindsight at %s" % cfg.url)
            conform_bank()
            return 0
        shell.start_services(cfg, os.environ)
        if not shell.wait_healthy(cfg):
            shell.die("API did not become healthy after 180s.",
                      "Check: atk logs hindsight")
        conform_bank()
        return 0
    if verb == "stop":
        if cfg.mode != "remote":
            shell.compose(cfg, "down", check=True)
        return 0
    if verb == "status":
        if cfg.mode == "remote":
            if not shell.api_healthy(cfg):
                shell.die("Cannot reach %s" % cfg.url,
                          "Check the URL and that the instance is running.")
            return 0
        result = shell.compose(cfg, "ps", "--filter", "status=running",
                               "--services", capture_output=True, text=True,
                               check=False)
        if "hindsight" not in result.stdout:
            shell.die("The hindsight container is not running.",
                      "Start it: atk start hindsight")
        if not shell.api_healthy(cfg):
            shell.die("The container is running but %s/health is not answering."
                      % cfg.url, "It may still be starting. Check: atk logs hindsight")
        return 0
    if verb == "logs":
        if cfg.mode == "remote":
            print("Logs live on the remote instance at %s" % cfg.url,
                  file=sys.stderr)
            return 1
        return shell.compose(cfg, "logs", "-f", check=False).returncode
    print("usage: service {start|stop|status|logs}", file=sys.stderr)
    return 2


# A failed `atk add` deletes the plugin directory and its manifest entry, so
# `atk install hindsight` answers "not found" to the person who most needs it.
# Every hint that asks for a retry names both commands.
RETRY = ("Then run the install again:",
         "  atk add hindsight       if you were adding it (a failed add removes the plugin)",
         "  atk install hindsight   if it was already added")


def install_fail(msg, *lines):
    print("", file=sys.stderr)
    print("  ❌ %s" % msg, file=sys.stderr)
    for line in lines:
        print("  %s" % line, file=sys.stderr)
    print("", file=sys.stderr)
    raise SystemExit(1)


def install(cfg):
    env = config.resolve_endpoints(cfg, os.environ)
    llm_model = env.get("HINDSIGHT_LLM_MODEL", "")
    llm_base_url = env.get("HINDSIGHT_LLM_BASE_URL", "")
    embedding_model = env.get("HINDSIGHT_EMBEDDING_MODEL", "")
    embedding_base_url = env.get("HINDSIGHT_EMBEDDING_BASE_URL", "")
    ui_url = cfg.url.rsplit(":", 1)[0] + ":9999"

    print("=== Hindsight Install ===")

    repaired = config.repair_env_url(cfg.plugin_dir)
    if repaired:
        print("  ✓ Dropped a trailing slash from HINDSIGHT_URL: %s" % repaired)

    if cfg.mode == "remote":
        if not shell.api_healthy(cfg):
            install_fail(
                "Cannot reach Hindsight at %s" % cfg.url,
                "Check the URL and that the instance is running.", *RETRY,
                "To run it on this machine instead: atk setup hindsight (HINDSIGHT_MODE=local)")
        print("  ✓ Reached %s" % cfg.url)
        conform_bank()
        check_llm(cfg)
        print("  ✅ Installed  (remote: %s)" % cfg.url)
        return 0

    if not env.get("HINDSIGHT_LLM_PROVIDER"):
        install_fail(
            "HINDSIGHT_LLM_PROVIDER is not set.",
            "It says where the extraction model runs.",
            "Set it: atk setup hindsight")

    if not llm_model:
        install_fail(
            "HINDSIGHT_LLM_MODEL is not set.",
            "This model extracts facts from every memory.",
            "Set it: atk setup hindsight   (see 'Model' in the README)")

    if not shell.which("docker"):
        install_fail("Docker is not installed.",
                     "Install Docker Desktop.", *RETRY)
    docker_info = shell.run(["docker", "info"], capture_output=True, check=False)
    if docker_info.returncode != 0:
        install_fail("Docker is not running.",
                     "Start Docker Desktop.", *RETRY)
    print("  ✓ Docker is running")

    # The model check queries Ollama's own API, so it only applies when the
    # endpoint is a local Ollama. A hosted provider validates on first use.
    if config.is_local_ollama(llm_base_url) or config.is_local_ollama(embedding_base_url):
        try:
            tags = json.loads(
                client.http("GET", "http://localhost:11434/api/tags", timeout=5))
            installed = [model["name"] for model in tags["models"]]
        except Exception:
            install_fail("Ollama is not responding on http://localhost:11434",
                         "Start it.", *RETRY,
                         "Or point Hindsight at another provider: atk setup hindsight")
        print("  ✓ Ollama reachable")

        def check_model(name):
            # Ollama resolves an untagged name to ':latest'.
            want = name if ":" in name else name + ":latest"
            if want in installed:
                print("  ✓ Model '%s' available" % name)
                return
            install_fail("Model '%s' is not available in Ollama." % want,
                         "Pull it:          ollama pull %s" % name,
                         "Or pick another:  atk setup hindsight",
                         *RETRY,
                         "",
                         "Available:",
                         *["    %s" % model for model in installed])

        if config.is_local_ollama(llm_base_url):
            check_model(llm_model)
        if config.is_local_ollama(embedding_base_url):
            check_model(embedding_model)

        # Ollama bound to 127.0.0.1 is reachable from the host but not from a
        # container, which would otherwise surface at the first retain.
        reach = shell.run(
            ["docker", "run", "--rm", "--add-host=host.docker.internal:host-gateway",
             "curlimages/curl:8.11.1", "-sf", "--max-time", "10",
             "http://host.docker.internal:11434/api/version"],
            capture_output=True, check=False)
        if reach.returncode != 0:
            install_fail("A container cannot reach Ollama at host.docker.internal:11434.",
                         "Bind Ollama to all interfaces, then restart it:",
                         "    launchctl setenv OLLAMA_HOST 0.0.0.0:11434")
        print("  ✓ Container reaches host Ollama")

    shell.compose(cfg, "pull", check=True)
    shell.compose(cfg, "up", "-d", check=True)

    # First boot runs database migrations and downloads the reranker weights.
    if not shell.wait_healthy(cfg):
        # The container outlives the plugin directory a failed add removes.
        install_fail("API did not become healthy after 180s.",
                     "Check: docker logs hindsight", *RETRY)
    conform_bank()
    check_llm(cfg)

    print("  ✅ API      %s" % cfg.url)
    print("  ✅ MCP      %s/mcp" % cfg.url)

    ui_ok = False
    for _ in range(15):
        try:
            client.http("GET", ui_url, timeout=5)
            ui_ok = True
            break
        except Exception:
            shell.sleep(2)
    if ui_ok:
        print("  ✅ Web UI   %s" % ui_url)
    else:
        print("  ⚠️  Web UI not responding — check: atk logs hindsight")

    print("  ✅ Installed  (LLM: %s · embeddings: %s)" % (llm_model, embedding_model))
    return 0


def uninstall(cfg):
    print("=== Hindsight Uninstall ===")
    if cfg.mode == "remote":
        print("  ✅ Uninstalled — remote mode ran nothing locally.")
        print("  The instance at %s is untouched." % cfg.url)
        return 0

    down = shell.compose(cfg, "down", "--rmi", "all", capture_output=True, check=False)
    if down.returncode != 0:
        reason = (down.stderr or "").strip().splitlines()
        install_fail("Could not remove the container and image.", *reason[-1:],
                     "Start Docker Desktop, then: atk remove hindsight")
    print("  ✓ Container and image removed")

    # Reranker weights are a re-downloadable cache, not user data.
    models = shell.run(["docker", "volume", "rm", cfg.models_volume_name],
                       capture_output=True, check=False)
    if models.returncode == 0:
        print("  ✓ Cached model weights removed")

    volume = shell.run(["docker", "volume", "inspect", cfg.volume_name],
                       capture_output=True, check=False)
    if volume.returncode == 0:
        print("")
        print("  Volume '%s' holds every memory Hindsight has stored."
              % cfg.volume_name)
        if shell.confirm("Delete it permanently?"):
            removed = shell.run(["docker", "volume", "rm", cfg.volume_name],
                                capture_output=True, check=False)
            if removed.returncode != 0:
                reason = (removed.stderr or "").strip().splitlines()
                install_fail("Memories were not deleted.", *reason[-1:],
                             "Remove them yourself: docker volume rm %s" % cfg.volume_name)
            print("  ✓ Memories deleted")
        else:
            print("  Memories kept in volume '%s'." % cfg.volume_name)
            print("  Reinstalling picks them up again; delete later with:")
            print("      docker volume rm %s" % cfg.volume_name)

    print("  ✅ Uninstalled")
    return 0
