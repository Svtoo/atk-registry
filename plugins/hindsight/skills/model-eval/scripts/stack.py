#!/usr/bin/env python3
"""The EVAL_* exports for one arm on one production snapshot, key excluded.

    eval "$(python3 stack.py --run-dir <run-dir> --provider <p> --model <m> \\
            --base-url <u> --strict-schema true|false --max-concurrent <n> [--pin '<json list>'])"

One `export` line per variable compose.py interpolates:

  EVAL_LLM_PROVIDER, EVAL_LLM_MODEL   the arm's, verbatim.
  EVAL_LLM_BASE_URL                   the arm's. An ollama arm that leaves it
                                      empty gets the host's Ollama: the
                                      provider default names localhost, which
                                      inside the container is the container.
  EVAL_LLM_EXTRA_BODY                 {"provider":{"only":<pin>}} for an
                                      openrouter arm, null for every other.
  EVAL_LLM_STRICT_SCHEMA              the arm's.
  EVAL_LLM_MAX_CONCURRENT             the arm's.
  EVAL_REFLECT_LLM_EXTRA_BODY         only when the snapshot sets
                                      HINDSIGHT_API_REFLECT_LLM_EXTRA_BODY:
                                      production's fields with `provider`
                                      dropped, and the arm's pin put back as
                                      `provider` for an openrouter arm.

A pin is required for an openrouter arm and refused for any other provider.
The key is not here: the dispatcher exports EVAL_LLM_API_KEY itself, so a
secret never passes through a printed line.
"""
import argparse
import json
import os
import shlex
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import snapshot  # noqa: E402

OLLAMA_HOST_URL = "http://host.docker.internal:11434/v1"
REFLECT_VAR = "HINDSIGHT_API_REFLECT_LLM_EXTRA_BODY"


def die(msg):
    print(f"FATAL: {msg}", file=sys.stderr)
    sys.exit(1)


def parse_pin(raw):
    try:
        pin = json.loads(raw)
    except ValueError as error:
        die(f"--pin is not JSON: {error}")
    if not (isinstance(pin, list) and pin and all(isinstance(x, str) and x for x in pin)):
        die(f"--pin must be a non-empty JSON list of endpoint tags, got: {raw}")
    return pin


def reflect_body(raw, pin):
    """Production's reflect extra body with its provider pin swapped for the arm's."""
    try:
        body = json.loads(raw)
    except ValueError as error:
        die(f"production {REFLECT_VAR} is not JSON: {error}")
    if body is None:
        return "null"
    if not isinstance(body, dict):
        die(f"production {REFLECT_VAR} is not a JSON object: {raw[:80]!r}")
    body = {key: value for key, value in body.items() if key != "provider"}
    if pin:
        body["provider"] = {"only": pin}
    return json.dumps(body, separators=(",", ":"))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--run-dir", required=True, help="directory holding prod.json")
    ap.add_argument("--provider", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--base-url", default="")
    ap.add_argument("--strict-schema", required=True, choices=("true", "false"))
    ap.add_argument("--max-concurrent", required=True, type=int)
    ap.add_argument("--pin", help="JSON list of OpenRouter endpoint tags")
    args = ap.parse_args()

    if not args.provider.strip() or not args.model.strip():
        die("provider and model must not be empty")
    if args.max_concurrent < 1:
        die(f"max_concurrent must be >= 1, got {args.max_concurrent}")
    pin = None
    if args.provider == "openrouter":
        if not args.pin:
            die("an openrouter arm needs --pin; build one with: model-eval pin <arm>")
        pin = parse_pin(args.pin)
    elif args.pin:
        die(f"--pin is an OpenRouter concept; provider {args.provider!r} takes none")
    base_url = args.base_url
    if args.provider == "ollama" and not base_url:
        base_url = OLLAMA_HOST_URL
    extra_body = json.dumps({"provider": {"only": pin}}, separators=(",", ":")) if pin else "null"

    env = snapshot.container_env(snapshot.load_container(args.run_dir))
    exports = [
        ("EVAL_LLM_PROVIDER", args.provider),
        ("EVAL_LLM_MODEL", args.model),
        ("EVAL_LLM_BASE_URL", base_url),
        ("EVAL_LLM_EXTRA_BODY", extra_body),
        ("EVAL_LLM_STRICT_SCHEMA", args.strict_schema),
        ("EVAL_LLM_MAX_CONCURRENT", str(args.max_concurrent)),
    ]
    if REFLECT_VAR in env:
        exports.append(("EVAL_REFLECT_LLM_EXTRA_BODY", reflect_body(env[REFLECT_VAR], pin)))
    for name, value in exports:
        print(f"export {name}={shlex.quote(value)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
