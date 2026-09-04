#!/usr/bin/env python3
"""Capture production's state into a run directory, and read it back.

A run is compared against the production it was copied from, never against
whatever production is doing when the comparison happens: an exclusive arm
stops production for its duration, and production's own settings move between
runs. So ingest captures two files before anything else starts, and compose.py,
parity.py, stack.py and arm.py read those for the rest of the run's life, the
read side included.

  prod.json       docker inspect of the production container, as docker prints
                  it, with every credential in its environment replaced by
                  <redacted>.
  prod-bank.json  the production bank's config endpoint response.

    python3 snapshot.py --run-dir <dir> --prod-container hindsight \\
                        --prod-api http://localhost:8888 --bank default
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request

CONTAINER_FILE = "prod.json"
BANK_FILE = "prod-bank.json"
ENV_PREFIXES = ("HINDSIGHT_", "HF_")
# A name that carries a credential. TOKEN counts only as a whole word, so a
# count such as MAX_COMPLETION_TOKENS is copied rather than redacted.
SECRET_NAME = re.compile(r"API_KEY|_KEY$|SECRET|PASSWORD|TOKEN$|_TOKEN_")
# Values that are not credentials even under a credential's name.
PLACEHOLDERS = ("", "not-needed")
REDACTED = "<redacted>"


def die(msg):
    print(f"FATAL: {msg}", file=sys.stderr)
    sys.exit(1)


def is_secret(name, value):
    return bool(SECRET_NAME.search(name)) and value not in PLACEHOLDERS


def redact_env(entries):
    out = []
    for entry in entries:
        name, sep, value = entry.partition("=")
        out.append(f"{name}={REDACTED}" if sep and is_secret(name, value) else entry)
    return out


def inspect(container):
    out = subprocess.run(["docker", "inspect", container], capture_output=True, text=True)
    if out.returncode:
        die(f"cannot inspect container {container!r}: {out.stderr.strip()[:200]}")
    data = json.loads(out.stdout)
    if len(data) != 1:
        die(f"docker inspect {container!r} returned {len(data)} objects")
    status = data[0]["State"].get("Status")
    if status != "running":
        die(f"container {container!r} is {status!r}, not running")
    data[0]["Config"]["Env"] = redact_env(data[0]["Config"]["Env"])
    return data


def fetch_bank(api, bank):
    url = f"{api}/v1/default/banks/{bank}/config"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            payload = json.load(resp)
    except Exception as error:
        die(f"production bank config is unreachable at {url}: {error}")
    if not isinstance(payload, dict) or not isinstance(payload.get("config"), dict):
        die(f"{url} returned no config object")
    return payload


def write(run_dir, name, payload):
    path = os.path.join(run_dir, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")
    return path


def load_container(run_dir):
    """The inspect object recorded in the run's prod.json."""
    path = os.path.join(run_dir, CONTAINER_FILE)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError as error:
        die(f"no production snapshot at {path}: {error}")
    if not isinstance(data, list) or len(data) != 1:
        die(f"{path} is not the docker inspect output of one container")
    return data[0]


def container_env(info, prefixes=ENV_PREFIXES):
    env = {}
    for entry in info["Config"]["Env"]:
        key, sep, value = entry.partition("=")
        if sep and key.startswith(prefixes):
            env[key] = value
    return env


def load_bank_config(run_dir):
    """The production bank config recorded in the run's prod-bank.json."""
    path = os.path.join(run_dir, BANK_FILE)
    try:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
    except OSError as error:
        die(f"no production bank snapshot at {path}: {error}")
    config = payload.get("config") if isinstance(payload, dict) else None
    if not isinstance(config, dict):
        die(f"{path} holds no config object")
    return config


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--prod-container", required=True)
    ap.add_argument("--prod-api", required=True)
    ap.add_argument("--bank", required=True)
    args = ap.parse_args()
    if not os.path.isdir(args.run_dir):
        die(f"run directory does not exist: {args.run_dir}")
    for name in (CONTAINER_FILE, BANK_FILE):
        if os.path.exists(os.path.join(args.run_dir, name)):
            die(f"{args.run_dir} already holds {name}; a snapshot is taken once per run")
    info = inspect(args.prod_container)
    bank = fetch_bank(args.prod_api, args.bank)
    container_path = write(args.run_dir, CONTAINER_FILE, info)
    bank_path = write(args.run_dir, BANK_FILE, bank)
    env = container_env(info[0])
    print(f"  snapshot of {args.prod_container} ({info[0]['Config']['Image']}): "
          f"{container_path} ({len(env)} HINDSIGHT_/HF_ variables), {bank_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
