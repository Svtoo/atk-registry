"""Plugin configuration and LLM/embedding endpoint resolution."""
import os
import sys

SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_DIR = os.path.dirname(SRC_DIR)
HOST_OLLAMA = "http://host.docker.internal:11434/v1"
EMBEDDING_MODEL_DEFAULT = "mxbai-embed-large"
MODES = ("local", "remote")


def _die(msg, hint):
    print("  ❌ %s" % msg, file=sys.stderr)
    print("  %s" % hint, file=sys.stderr)
    raise SystemExit(1)


class Config:
    """Plugin configuration resolved from the environment."""

    def __init__(self, environ, plugin_dir=None):
        mode = (environ.get("HINDSIGHT_MODE") or "local").strip().lower()
        if mode not in MODES:
            _die("HINDSIGHT_MODE %r is not one of %s." % (mode, ", ".join(MODES)),
                 "Fix it: atk setup hindsight")
        self.mode = mode
        self.url = (environ.get("HINDSIGHT_URL")
                    or "http://localhost:8888").rstrip("/")
        self.bank = environ.get("HINDSIGHT_BANK") or "default"
        self.volume_name = environ.get("HINDSIGHT_VOLUME_NAME") or "hindsight_data"
        self.models_volume_name = self.volume_name + "_models"
        self.backup_dir = environ.get("HINDSIGHT_BACKUP_DIR") or ""
        self.plugin_dir = plugin_dir or PLUGIN_DIR


def resolve_endpoints(cfg, environ):
    """Returns the environment with LLM/embedding endpoints resolved the way
    the container will see them; a user-supplied URL always wins."""
    env = dict(environ)
    if not env.get("HINDSIGHT_EMBEDDING_MODEL"):
        env["HINDSIGHT_EMBEDDING_MODEL"] = EMBEDDING_MODEL_DEFAULT
    if cfg.mode != "local":
        return env
    if (not env.get("HINDSIGHT_LLM_BASE_URL")
            and env.get("HINDSIGHT_LLM_PROVIDER") == "ollama"):
        env["HINDSIGHT_LLM_BASE_URL"] = HOST_OLLAMA
    if not env.get("HINDSIGHT_EMBEDDING_BASE_URL"):
        env["HINDSIGHT_EMBEDDING_BASE_URL"] = HOST_OLLAMA
    return env


def repair_env_url(plugin_dir):
    """Strips trailing slashes from HINDSIGHT_URL in the plugin's .env, the
    copy ATK reads to build the agent's MCP endpoint, where the server answers
    a double slash with a 404. Returns the repaired value, or None."""
    path = os.path.join(plugin_dir, ".env")
    try:
        with open(path) as fh:
            lines = fh.readlines()
    except OSError:
        return None
    repaired = None
    for index, line in enumerate(lines):
        name, sep, raw = line.partition("=")
        if not sep or name.strip() != "HINDSIGHT_URL":
            continue
        value = raw.rstrip("\n")
        newline = raw[len(value):]
        quote = value[:1] if value[:1] in "\"'" and value.endswith(value[:1]) else ""
        inner = value[len(quote):len(value) - len(quote)] if quote else value
        if not inner.endswith("/"):
            continue
        repaired = inner.rstrip("/")
        lines[index] = "%s%s%s%s%s%s" % (name, sep, quote, repaired, quote, newline)
    if repaired is not None:
        with open(path, "w") as fh:
            fh.writelines(lines)
    return repaired


def is_local_ollama(url):
    return bool(url) and any(host in url for host in (
        "//localhost:11434", "//127.0.0.1:11434", "//host.docker.internal:11434"))
