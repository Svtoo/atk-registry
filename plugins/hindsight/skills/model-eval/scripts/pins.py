#!/usr/bin/env python3
"""Propose a provider pin for one OpenRouter arm.

Two filters, each load-bearing:

  quantization        fp8 or better (fp8, bf16, fp16, fp32). fp4 and below is a
                      different model, not a cheaper one: letting an arm land on
                      it compares quantisations, not models. "unknown" cannot be
                      checked, so it is out too.
  structured_outputs  listed in supported_parameters. Strict schema is the
                      point of the stack; a host without it silently falls back
                      to "please return JSON".

Production's own hosts, read live from the container's
HINDSIGHT_API_LLM_EXTRA_BODY, are preferred, not excluded: the eval exists to
measure the stack that will be deployed, and a host production never uses
measures something else. Sharing a host shares its rate limit; the eval runs
at production's own concurrency and retries, and a burst of 429s shows up as
failed operations, never as a quietly different number.

No residency filter: the corpus is synthetic. Production keeps its own
residency pin because that is real memory; this is not.

The proposal is production's hosts that serve the model, then the best of the
rest by uptime. Confirm it with the user, then pass it to ingest --pin. A pin
is built per run: hosts, prices and production's own pin all move, so a pin
from an earlier run is a record, not an input.

A pin is an OpenRouter concept, and the endpoint listing is read with the
plugin's own key, so this runs only for an openrouter arm on an openrouter
production; anything else stops with a message.

    python3 pins.py glm53flash
    python3 pins.py glm53flash --json      # the proposed pin only
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import armsfile  # noqa: E402

PROD_CONTAINER = "hindsight"
ENDPOINTS = "https://openrouter.ai/api/v1/models/{model}/endpoints"
ACCEPTED_QUANT = ("fp8", "bf16", "fp16", "fp32")
TOP = 4


def die(msg):
    print(f"FATAL: {msg}", file=sys.stderr)
    sys.exit(1)


def plugin_key():
    provider = os.environ.get("HINDSIGHT_LLM_PROVIDER")
    if provider != "openrouter":
        die(f"the plugin key is for {provider!r}, and the OpenRouter endpoint listing needs an "
            f"OpenRouter key; pins can only be built on an openrouter production")
    key = os.environ.get("HINDSIGHT_LLM_API_KEY")
    if not key:
        die("HINDSIGHT_LLM_API_KEY is not set in the plugin environment")
    return key


def production_hosts(container):
    out = subprocess.run(["docker", "inspect", container, "--format", "{{json .Config.Env}}"],
                         capture_output=True, text=True)
    if out.returncode:
        die(f"cannot inspect container {container!r}: {out.stderr.strip()[:200]}")
    raw = None
    for entry in json.loads(out.stdout):
        key, sep, value = entry.partition("=")
        if sep and key == "HINDSIGHT_API_LLM_EXTRA_BODY":
            raw = value
    if raw is None:
        die(f"container {container!r} has no HINDSIGHT_API_LLM_EXTRA_BODY")
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as error:
        die(f"production HINDSIGHT_API_LLM_EXTRA_BODY is not JSON: {error}")
    provider = (body or {}).get("provider") or {}
    tags = list(provider.get("only") or []) + list(provider.get("order") or [])
    hosts = sorted({tag.split("/", 1)[0] for tag in tags})
    if not hosts:
        die("production pins no hosts; the exclusion filter would be empty")
    return hosts


def endpoints(model, api_key):
    req = urllib.request.Request(ENDPOINTS.format(model=model),
                                 headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as error:
        die(f"OpenRouter returned {error.code} for {model!r}: {error.read()[:200].decode(errors='replace')}")
    eps = (data.get("data") or {}).get("endpoints") or []
    if not eps:
        die(f"OpenRouter lists no endpoints for {model!r}")
    return eps


def verdict(ep):
    quant = ep.get("quantization") or "unknown"
    reasons = []
    if quant not in ACCEPTED_QUANT:
        reasons.append(f"quantization {quant}")
    if "structured_outputs" not in (ep.get("supported_parameters") or []):
        reasons.append("no structured_outputs")
    return reasons


def per_million(ep, field):
    value = (ep.get("pricing") or {}).get(field)
    return float(value) * 1e6 if value not in (None, "") else float("nan")


def main():
    ap = argparse.ArgumentParser(description="propose a provider pin for an OpenRouter arm")
    ap.add_argument("arm", help="arm key or id from arms.yaml")
    ap.add_argument("--top", type=int, default=TOP, help="hosts in the proposed pin")
    ap.add_argument("--json", action="store_true", help="print only the proposed pin")
    ap.add_argument("--prod-container", default=PROD_CONTAINER)
    args = ap.parse_args()

    try:
        arm = armsfile.find(args.arm)
    except armsfile.ArmsError as error:
        die(str(error))
    if arm["provider"] != "openrouter":
        die(f"arm {arm['key']!r} runs on {arm['provider']!r}; a pin is an OpenRouter concept "
            f"and this arm takes none")
    model = arm["model"]
    api_key = plugin_key()
    prod_hosts = production_hosts(args.prod_container)
    eps = endpoints(model, api_key)

    rows = []
    for ep in eps:
        tag = ep.get("tag") or ""
        uptime = ep.get("uptime_last_30m")
        rows.append({
            "tag": tag,
            "production": tag.split("/", 1)[0] in prod_hosts,
            "quant": ep.get("quantization") or "unknown",
            "structured": "structured_outputs" in (ep.get("supported_parameters") or []),
            "uptime": float(uptime) if uptime is not None else None,
            "status": ep.get("status"),
            "prompt": per_million(ep, "prompt"),
            "completion": per_million(ep, "completion"),
            "context": ep.get("context_length"),
            "reasons": verdict(ep),
        })

    candidates = [r for r in rows if not r["reasons"]]
    # Production's hosts first, then deranked hosts (negative status) last: OpenRouter will not route to them.
    candidates.sort(key=lambda r: (r["production"], (r["status"] or 0) >= 0,
                                   r["uptime"] if r["uptime"] is not None else -1.0, -r["prompt"]), reverse=True)
    proposed = [r["tag"] for r in candidates[:args.top]]
    if not proposed:
        die(f"no endpoint of {model!r} passes both filters")

    if args.json:
        print(json.dumps(proposed))
        return 0

    print(f"\n  {arm['key']} = {model}: {len(eps)} endpoints; production pins {', '.join(prod_hosts)}")
    print(f"\n  {'tag':<20}{'quant':<9}{'struct':<8}{'up30m':>7}{'status':>7}{'$/M in':>9}{'$/M out':>9}{'ctx':>10}  verdict")
    for r in sorted(rows, key=lambda r: (bool(r["reasons"]), not r["production"], -(r["uptime"] or -1.0))):
        up = f"{r['uptime']:.2f}" if r["uptime"] is not None else "none"
        note = "rejected: " + ", ".join(r["reasons"]) if r["reasons"] else \
               "candidate, production host" if r["production"] else "candidate"
        print(f"  {r['tag']:<20}{r['quant']:<9}{'yes' if r['structured'] else 'no':<8}{up:>7}"
              f"{str(r['status']):>7}{r['prompt']:>9.3f}{r['completion']:>9.3f}{str(r['context']):>10}  {note}")

    deranked = [r["tag"] for r in candidates[:args.top] if (r["status"] or 0) < 0]
    print(f"\n  proposed pin, production's hosts first, then top candidates by uptime ({len(proposed)}):")
    print(f"  {json.dumps(proposed)}")
    if deranked:
        print(f"  WARNING: {', '.join(deranked)} carry a negative status; OpenRouter may not route to them")
    print(f"\n  Confirm with the user, then:  model-eval ingest {arm['key']} --pin '" + json.dumps(proposed) + "'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
