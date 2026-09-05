#!/usr/bin/env python3
"""Emit the eval compose file from the run's production snapshot.

The eval stack is production's stack plus the differences a second instance
forces, and nothing else. Reading the snapshot ingest took (prod.json, written
by snapshot.py) rather than the plugin's compose files means the copy cannot
drift: the image, every HINDSIGHT_* and HF_* variable, the resource limits,
the extra hosts and the healthcheck come from `docker inspect` and are written
back verbatim. Reading the snapshot rather than the live container means every
step of a run, the read side included, generates against the production the
run was copied from, whether or not production is up at the time.

Permitted differences, the same list parity.py checks the running result
against:

  identity   container name, compose project, worker id
  ports      host ports moved up by PORT_OFFSET
  volumes    separate named volumes
  restart    "no": an eval container must not come back by itself
  model      provider, model, base url, key, extra_body, strict schema and
             max concurrent come from EVAL_*, exported by the dispatcher
  reflect    HINDSIGHT_API_REFLECT_LLM_EXTRA_BODY comes from EVAL_* when the
             snapshot sets it, and is absent when it does not
  knobs      HINDSIGHT_API_REFLECT_WALL_TIMEOUT accepts an EVAL_* override and
             defaults to production's value

    python3 compose.py --run-dir <run-dir> --out <run-dir>/docker-compose.yml
    python3 compose.py --run-dir <run-dir> --print
"""
import argparse
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import snapshot  # noqa: E402

EVAL_NAME = "hindsight-eval"
PORT_OFFSET = 10000
VOLUME_PREFIX = "hindsight_eval_"

UNDER_TEST = [
    ("HINDSIGHT_API_LLM_PROVIDER", "${EVAL_LLM_PROVIDER:?ingest exports EVAL_LLM_PROVIDER}"),
    ("HINDSIGHT_API_LLM_MODEL", "${EVAL_LLM_MODEL:?ingest exports EVAL_LLM_MODEL}"),
    ("HINDSIGHT_API_LLM_BASE_URL", "${EVAL_LLM_BASE_URL:-}"),
    ("HINDSIGHT_API_LLM_API_KEY", "${EVAL_LLM_API_KEY:-not-needed}"),
    ("HINDSIGHT_API_LLM_EXTRA_BODY", "${EVAL_LLM_EXTRA_BODY:-null}"),
    ("HINDSIGHT_API_LLM_STRICT_SCHEMA", "${EVAL_LLM_STRICT_SCHEMA:?ingest exports EVAL_LLM_STRICT_SCHEMA}"),
    ("HINDSIGHT_API_LLM_MAX_CONCURRENT", "${EVAL_LLM_MAX_CONCURRENT:?ingest exports EVAL_LLM_MAX_CONCURRENT}"),
]
UNDER_TEST_IF_SET = [
    ("HINDSIGHT_API_REFLECT_LLM_EXTRA_BODY",
     "${EVAL_REFLECT_LLM_EXTRA_BODY:?ingest exports EVAL_REFLECT_LLM_EXTRA_BODY}"),
]
KNOBS = [
    ("HINDSIGHT_API_REFLECT_WALL_TIMEOUT", "EVAL_REFLECT_WALL_TIMEOUT"),
]
WORKER_ID_VAR = "HINDSIGHT_API_WORKER_ID"


def die(msg):
    print(f"FATAL: {msg}", file=sys.stderr)
    sys.exit(1)


def yaml_string(value):
    """A double-quoted YAML scalar carrying `value` byte for byte."""
    out = []
    for ch in value:
        code = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif code < 0x20 or code == 0x7F:
            out.append(f"\\u{code:04x}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def literal(value):
    """A copied value: compose must not interpolate anything inside it."""
    return yaml_string(value.replace("$", "$$"))


def size(num_bytes):
    if num_bytes % (1 << 30) == 0:
        return f"{num_bytes >> 30}g"
    if num_bytes % (1 << 20) == 0:
        return f"{num_bytes >> 20}m"
    return str(num_bytes)


def duration(ns):
    if ns % 10**9 == 0:
        return f"{ns // 10**9}s"
    return f"{ns // 10**6}ms"


def prod_env(info):
    env = snapshot.container_env(info)
    if not env:
        die(f"the production snapshot carries no {'/'.join(snapshot.ENV_PREFIXES)} variables")
    return env


def ports(info):
    bindings = info["HostConfig"].get("PortBindings") or {}
    if not bindings:
        die("production publishes no ports")
    out = []
    for spec, binds in sorted(bindings.items()):
        port, _, proto = spec.partition("/")
        if proto != "tcp":
            die(f"unexpected protocol in port binding {spec!r}")
        for bind in binds:
            host_port = int(bind["HostPort"]) + PORT_OFFSET
            host_ip = bind.get("HostIp") or ""
            prefix = f"{host_ip}:" if host_ip else ""
            out.append(f"{prefix}{host_port}:{port}")
    return out


def volumes(info):
    out = []
    for mount in info.get("Mounts") or []:
        if mount.get("Type") != "volume":
            die(f"production mounts a {mount.get('Type')!r} at {mount.get('Destination')!r}; "
                "only named volumes can be mirrored")
        name = mount["Name"]
        eval_name = VOLUME_PREFIX + (name[len("hindsight_"):] if name.startswith("hindsight_") else name)
        out.append((eval_name, mount["Destination"]))
    if not out:
        die("production mounts no volumes")
    return out


def render(info, source):
    image = info["Config"]["Image"]
    env = prod_env(info)
    fixed = {k for k, _ in UNDER_TEST} | {k for k, _ in UNDER_TEST_IF_SET} | {k for k, _ in KNOBS} | {WORKER_ID_VAR}
    missing = [k for k, _ in KNOBS if k not in env] + ([WORKER_ID_VAR] if WORKER_ID_VAR not in env else [])
    if missing:
        die(f"production env lacks {missing}; the eval cannot mirror a variable production does not set")

    lines = [
        f"# Generated by compose.py from the production snapshot {source} ({image}).",
        "# Every value not marked DIFFERS is production's own. Regenerate, never edit.",
        f"# generated: {datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')}",
        f"name: {EVAL_NAME}",
        "",
        "services:",
        f"  {EVAL_NAME}:",
        f"    image: {yaml_string(image)}",
        f"    container_name: {EVAL_NAME}",
        '    restart: "no"  # DIFFERS',
    ]
    memory = info["HostConfig"].get("Memory") or 0
    if memory:
        lines.append(f"    mem_limit: {size(memory)}")
    nano_cpus = info["HostConfig"].get("NanoCpus") or 0
    if nano_cpus:
        cpus = nano_cpus / 10**9
        lines.append(f"    cpus: {int(cpus) if cpus == int(cpus) else cpus}")
    lines.append("    ports:  # DIFFERS")
    for mapping in ports(info):
        lines.append(f"      - {yaml_string(mapping)}")
    lines.append("    volumes:  # DIFFERS")
    vols = volumes(info)
    for eval_name, destination in vols:
        lines.append(f"      - {yaml_string(eval_name + ':' + destination)}")
    extra_hosts = info["HostConfig"].get("ExtraHosts") or []
    if extra_hosts:
        lines.append("    extra_hosts:")
        for host in extra_hosts:
            lines.append(f"      - {yaml_string(host)}")

    lines.append("    environment:")
    lines.append(f"      {WORKER_ID_VAR}: {yaml_string(EVAL_NAME)}  # DIFFERS")
    for key, expr in UNDER_TEST:
        lines.append(f"      {key}: {yaml_string(expr)}  # DIFFERS")
    for key, expr in UNDER_TEST_IF_SET:
        if key in env:
            lines.append(f"      {key}: {yaml_string(expr)}  # DIFFERS")
    for key, override in KNOBS:
        default = env[key]
        if any(ch in default for ch in "${}"):
            die(f"production {key}={default!r} cannot be a compose interpolation default")
        lines.append(f"      {key}: {yaml_string('${' + override + ':-' + default + '}')}  # DIFFERS when set")
    for key in sorted(env):
        if key in fixed:
            continue
        value = env[key]
        if snapshot.is_secret(key, value):
            die(f"refusing to write production's {key} into a compose file on disk")
        lines.append(f"      {key}: {literal(value)}")

    health = info["Config"].get("Healthcheck")
    if health:
        lines.append("    healthcheck:")
        lines.append(f"      test: {json.dumps(health['Test'])}")
        for field, key in (("Interval", "interval"), ("Timeout", "timeout"),
                           ("StartPeriod", "start_period")):
            if health.get(field):
                lines.append(f"      {key}: {duration(health[field])}")
        if health.get("Retries"):
            lines.append(f"      retries: {health['Retries']}")

    lines.append("")
    lines.append("volumes:")
    for eval_name, _ in vols:
        lines.append(f"  {eval_name}:")
        lines.append(f"    name: {eval_name}")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--run-dir", required=True, help="directory holding prod.json")
    ap.add_argument("--out", help="write the compose file here")
    ap.add_argument("--print", action="store_true", help="write the compose file to stdout")
    args = ap.parse_args()
    if not args.out and not args.print:
        ap.error("pass --out <path> or --print")

    info = snapshot.load_container(args.run_dir)
    if info["State"].get("Status") != "running":
        die(f"the snapshot shows production {info['State'].get('Status')!r}, not running")
    text = render(info, os.path.join(args.run_dir, snapshot.CONTAINER_FILE))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"  wrote {args.out} from {info['Config']['Image']}")
    if args.print:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
