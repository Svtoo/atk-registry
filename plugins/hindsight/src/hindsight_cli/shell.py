"""Process execution, docker/compose access, host integration, and the
embedded-postgres instance for the hindsight plugin CLI."""
import contextlib
import datetime
import errno
import fcntl
import functools
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error

from . import client, config

DUMP_PREFIX = "hindsight_backup_"
# The version suffix is optional so dumps written before it still rotate.
DUMP_STAMP = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})_\d{4}(?:_hs[A-Za-z0-9._-]*)?\.dump$")
VERSION_CHARS = re.compile(r"[^A-Za-z0-9._-]")
# How many dumps survive: the newest of each of these many days, ISO weeks and
# months. They overlap, so the folder settles well under their sum.
KEEP_DAYS = 3
KEEP_WEEKS = 2
KEEP_MONTHS = 2
PG_ROOT = "/home/hindsight/.pg0"

# Process, clock and lookup seams; tests replace these.
run = subprocess.run
now = datetime.datetime.now
now_utc = functools.partial(datetime.datetime.now, datetime.timezone.utc)
sleep = time.sleep
which = shutil.which


def compose_cmd(cfg):
    """The docker compose invocation, honouring custom/docker-compose.override.yml."""
    cmd = ["docker", "compose",
           "-f", os.path.join(cfg.plugin_dir, "docker-compose.yml")]
    override = os.path.join(cfg.plugin_dir, "custom", "docker-compose.override.yml")
    if os.path.isfile(override):
        cmd += ["-f", override]
    return cmd


def compose(cfg, *args, **kwargs):
    kwargs.setdefault("env", config.resolve_endpoints(cfg, os.environ))
    return run(compose_cmd(cfg) + list(args), **kwargs)


def die(msg, hint=None):
    print("  ❌ %s" % msg, file=sys.stderr)
    if hint:
        print("  %s" % hint, file=sys.stderr)
    raise SystemExit(1)


def warn(msg):
    print("  ⚠ %s" % msg, file=sys.stderr)


def confirm(prompt):
    """True on an interactive yes; declines without a terminal."""
    if not sys.stdin.isatty():
        print("  %s [y/N] n  (no terminal — declining)" % prompt)
        return False
    try:
        answer = input("  %s [y/N] " % prompt)
    except EOFError:
        return False
    return answer in ("y", "Y", "yes", "YES", "Yes")


def notify(title, text):
    try:
        subprocess.run(
            ["osascript", "-e",
             'display notification "%s" with title "%s"' % (text, title)],
            capture_output=True, check=False)
    except OSError:
        pass


def backup_lock_path(cfg):
    return os.path.join(cfg.plugin_dir, "custom", ".backup.lock")


def lock_holder(fd):
    line = os.read(fd, 200).decode(errors="replace").strip()
    fields = line.split()
    if len(fields) > 1 and fields[0] == "pid":
        return "Held by %s. Check it: ps -p %s" % (line, fields[1])
    return "Another process on this machine holds it."


@contextlib.contextmanager
def backup_lock(cfg):
    """Holds the machine's backup lock for the block. The kernel releases the
    lock when the process ends however it ends, so a killed run leaves a file
    behind but never blocks the next backup."""
    path = backup_lock_path(cfg)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as error:
        die("Cannot open the backup lock: %s" % error)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno not in (errno.EAGAIN, errno.EACCES):
                die("Cannot take the backup lock: %s" % error)
            die("Another backup is already running.", lock_holder(fd))
        os.ftruncate(fd, 0)
        os.write(fd, ("pid %d since %s\n" % (
            os.getpid(), now().strftime("%Y-%m-%d %H:%M:%S"))).encode())
        yield
    finally:
        os.close(fd)


def wait_healthy(cfg, tries=90):
    for _ in range(tries):
        try:
            client.http("GET", cfg.url + "/health", timeout=5)
            return True
        except Exception:
            sleep(2)
    return False


def api_healthy(cfg):
    try:
        client.http("GET", cfg.url + "/health", timeout=10)
        return True
    except Exception:
        return False


def container_id():
    result = run(["docker", "inspect", "-f", "{{.Id}}", "hindsight"],
                 capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def mcp_is_stateful(environ):
    return (environ.get("HINDSIGHT_MCP_STATELESS") or "true") != "true"


def start_services(cfg, environ):
    before = container_id()
    compose(cfg, "up", "-d", stdout=subprocess.DEVNULL, check=True)
    after = container_id()
    if after and before != after and mcp_is_stateful(environ):
        print("")
        print("  ⚠  Hindsight is running in a NEW container. Every MCP client still")
        print("     connected to the old one is now dead, and its memory tools will")
        print("     HANG SILENTLY until they time out rather than report an error.")
        print("")
        print("     Reconnect Hindsight in every open agent session (/mcp in Claude")
        print("     Code, or restart the session), then confirm a new line appears:")
        print("       docker logs hindsight | grep 'Created new transport'")
        print("")


def stop_services(cfg):
    """Stops the service when it is running."""
    result = compose(cfg, "ps", "--filter", "status=running", "--services",
                     capture_output=True, text=True, check=False)
    if "hindsight" in result.stdout:
        compose(cfg, "down", stdout=subprocess.DEVNULL, check=True)


def require_local_mode(cfg):
    if cfg.mode != "local":
        die("This command manages the local database volume.",
            "HINDSIGHT_MODE is 'remote'; manage the database where that instance runs.")


def require_backup_dir(cfg):
    if not cfg.backup_dir:
        die("HINDSIGHT_BACKUP_DIR is not set.", "Configure it: atk setup hindsight")
    if not os.path.isdir(cfg.backup_dir):
        die("Backup directory does not exist: %s" % cfg.backup_dir,
            "Create it: mkdir -p \"%s\"" % cfg.backup_dir)
    if not os.path.isabs(cfg.backup_dir):
        die("HINDSIGHT_BACKUP_DIR must be an absolute path: %s" % cfg.backup_dir)


def require_volume(cfg):
    result = run(["docker", "volume", "inspect", cfg.volume_name],
                 capture_output=True, check=False)
    if result.returncode != 0:
        die("Docker volume '%s' not found." % cfg.volume_name,
            "Install first: atk install hindsight")


def require_service_running():
    result = run(["docker", "exec", "hindsight", "true"],
                 capture_output=True, check=False)
    if result.returncode != 0:
        die("The hindsight container is not running.", "Start it: atk start hindsight")


class PgInstance:
    """Connection details for the embedded PostgreSQL, from pg0's instance file."""

    def __init__(self, instance_json):
        fields = json.loads(instance_json)
        versioned = os.path.join(fields["installation_dir"], fields["version"])
        self.bin_dir = os.path.join(versioned, "bin")
        # The bundled binaries link libraries shipped next to them, not the OS ones.
        self.lib_dir = os.path.join(versioned, "lib")
        self.data_dir = fields["data_dir"]
        self.port = str(fields["port"])
        self.user = fields["username"]
        self.password = fields["password"]
        self.database = fields["database"]


INSTANCE_GLOB = PG_ROOT + "/instances/*/instance.json"


def pg_instance_from_container():
    result = run(["docker", "exec", "hindsight", "sh", "-c", "cat " + INSTANCE_GLOB],
                 stdout=subprocess.PIPE, text=True, check=True)
    return result.stdout


def pg_instance_from_volume(cfg, image):
    """Reads the instance file straight off the volume, for use while the
    service is down."""
    result = run(["docker", "run", "--rm",
                  "-v", "%s:%s:ro" % (cfg.volume_name, PG_ROOT),
                  "--entrypoint", "sh", image, "-c", "cat " + INSTANCE_GLOB],
                 stdout=subprocess.PIPE, text=True, check=True)
    return result.stdout


def dump_paths(cfg):
    return sorted(glob.glob(
        os.path.join(glob.escape(cfg.backup_dir), DUMP_PREFIX + "*.dump")))


def partial_paths(cfg):
    """Half-written dumps. A run killed mid-dump leaves one behind, and only
    the next run is in a position to know it is dead."""
    return sorted(glob.glob(os.path.join(
        glob.escape(cfg.backup_dir), DUMP_PREFIX + "*.dump.partial")))


def server_version(cfg):
    """What the running server calls itself, for the dump's name."""
    try:
        body = client.http("GET", cfg.url + "/version", timeout=10)
        return json.loads(body).get("api_version")
    except (urllib.error.URLError, ValueError, OSError):
        return None


def dump_name(version, at):
    return "%s%s_hs%s.dump" % (DUMP_PREFIX, at.strftime("%Y-%m-%d_%H%M"),
                               VERSION_CHARS.sub("-", version))


def newest_dump(cfg):
    paths = dump_paths(cfg)
    return paths[-1] if paths else None


def dumps_are_fresh(cfg, at=None):
    """True while any dump is under a day old."""
    cutoff = ((at or now()) - datetime.timedelta(days=1)).timestamp()
    for path in dump_paths(cfg):
        try:
            if os.path.getmtime(path) > cutoff:
                return True
        except FileNotFoundError:
            continue
    return False


def prune_selection(paths):
    """Splits dump paths into deletions: everything but the newest per day,
    week and month within the tiers above."""
    dated = []
    for path in paths:
        match = DUMP_STAMP.search(path)
        if not match:
            continue
        try:
            day = datetime.date(*map(int, match.groups()))
        except ValueError:
            continue  # named like a dump, but no such date; not ours to delete
        dated.append((day, path))

    newest_per_day = {}
    for day, path in dated:
        if day not in newest_per_day or path > newest_per_day[day]:
            newest_per_day[day] = path
    days = sorted(newest_per_day.items(), reverse=True)

    def tier(key, limit):
        buckets = {}
        for day, path in days:
            buckets.setdefault(key(day), path)
        return [buckets[k] for k in sorted(buckets, reverse=True)[:limit]]

    keep = {path for _, path in days[:KEEP_DAYS]}
    keep.update(tier(lambda d: d.isocalendar()[:2], KEEP_WEEKS))
    keep.update(tier(lambda d: (d.year, d.month), KEEP_MONTHS))
    return [path for _, path in dated if path not in keep]


def human_size(path):
    size = os.path.getsize(path)
    for threshold, suffix in ((1 << 30, "G"), (1 << 20, "M"), (1 << 10, "K")):
        if size >= threshold:
            return "%d%s" % (round(size / threshold), suffix)
    return "%dB" % size


# The explicit PATH matters: launchd's default lacks the docker binary's dir.
PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
    <key>Label</key><string>%(label)s</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>%(plugin_dir)s/backup.sh</string>
        <string>--if-stale</string>
    </array>
    <key>StartInterval</key><integer>3600</integer>
    <key>RunAtLoad</key><true/>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
    <key>StandardOutPath</key><string>%(log_path)s</string>
    <key>StandardErrorPath</key><string>%(log_path)s</string>
</dict></plist>
"""


def render_plist(label, plugin_dir, log_path):
    return PLIST_TEMPLATE % {
        "label": label, "plugin_dir": plugin_dir, "log_path": log_path}
