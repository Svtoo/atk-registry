#!/usr/bin/env python3
"""Refuse to run an arm whose stack differs from production in any way that
changes what extraction produces.

The eval exists to answer a question about the production pipeline, so every
divergence from it is a silent lie in the result. Rather than trusting a
hand-maintained list of settings, this reads the production snapshot the run
was copied from (prod.json and prod-bank.json in the run directory, written by
snapshot.py) and the live eval container and bank, and demands equality
everywhere except an explicit, justified allow-list. The snapshot rather than
the live container, so every step of a run compares against one production
state, and the read side of an exclusive run can compare while production is
stopped.

    python3 parity.py --run-dir <run-dir> [eval-bank]

Exit 0 = safe to run. Exit 1 = drift, with the drift named.
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import snapshot  # noqa: E402

EVAL_CONTAINER = "hindsight-eval"
EVAL_API = "http://localhost:18888"

# Each entry must name why running a second instance forces the difference.
ENV_ALLOWED = {
    "HINDSIGHT_API_WORKER_ID":      "task recovery keys on worker id; sharing it lets each instance reclaim the other's rows",
    "HINDSIGHT_API_LLM_PROVIDER":   "the variable under test",
    "HINDSIGHT_API_LLM_MODEL":      "the variable under test",
    "HINDSIGHT_API_LLM_BASE_URL":   "follows the provider under test",
    "HINDSIGHT_API_LLM_API_KEY":    "follows the provider under test",
    "HINDSIGHT_API_LLM_EXTRA_BODY": "provider pin: the eval must not compete with production for the same rate-limited hosts",
    "HINDSIGHT_API_REFLECT_LLM_EXTRA_BODY": "production's reflect body with its provider pin swapped for the arm's own, for the same reason as HINDSIGHT_API_LLM_EXTRA_BODY",
    "HINDSIGHT_API_LLM_STRICT_SCHEMA": "follows the arm: a provider without schema enforcement measures JSON-mode extraction, the arm's note says so, and run.json records strict_schema false so the result is flagged not schema-comparable",
    "HINDSIGHT_API_REFLECT_WALL_TIMEOUT": "diagnostic: production's default 300s is what glm-5.2 and qwen fail against. Raised to locate the real ceiling; the failure at 300 is itself a recorded result.",
    "HINDSIGHT_API_LLM_MAX_CONCURRENT": "throughput only: production's 4 is sized for its US pin's rate limit, the eval pin has more capacity. Cannot change what a single extraction returns.",
}
BANK_ALLOWED = {
    "mcp_enabled_tools": "MCP surface is not part of extraction; no agent connects to the eval bank",
}
# Copied from production onto the eval bank so they cannot drift by omission.
BANK_COPIED = [
    "retain_extraction_mode", "retain_custom_instructions", "retain_mission",
    "retain_chunk_size", "retain_structured_chunk_size", "retain_chunk_batch_size",
    "retain_default_strategy", "retain_strategies", "store_document_text",
    "enable_observations", "enable_auto_consolidation",
    "consolidation_max_memories_per_round", "consolidation_llm_batch_size",
    "consolidation_llm_parallelism", "consolidation_source_facts_max_tokens",
    "consolidation_source_facts_max_tokens_per_observation",
    "observations_mission", "max_observations_per_scope", "observation_scope_limits",
    "entity_labels", "entities_allow_free_form", "memory_defense",
    "disposition_skepticism", "disposition_literalism", "disposition_empathy",
]


def container_env(name):
    out = subprocess.run(["docker", "inspect", name, "--format",
                          "{{range .Config.Env}}{{println .}}{{end}}"],
                         capture_output=True, text=True)
    if out.returncode:
        sys.exit(f"FATAL: cannot inspect container {name!r}: {out.stderr.strip()[:200]}")
    env = {}
    for line in out.stdout.splitlines():
        if line.startswith(snapshot.ENV_PREFIXES) and "=" in line:
            k, v = line.split("=", 1)
            env[k] = v
    return env


def prod_env(run_dir):
    return snapshot.container_env(snapshot.load_container(run_dir))


def bank_config(api, bank):
    with urllib.request.urlopen(f"{api}/v1/default/banks/{bank}/config", timeout=30) as r:
        return json.load(r).get("config", {})


def prod_bank_config(run_dir):
    """Production's bank config as ingest snapshotted it."""
    return snapshot.load_bank_config(run_dir)


def report(title, prod, eval_, allowed):
    drift = []
    for k in sorted(set(prod) | set(eval_)):
        a, b = prod.get(k, "<absent>"), eval_.get(k, "<absent>")
        if a == b:
            continue
        if k in allowed:
            print(f"  ok   {k}\n         allowed: {allowed[k]}")
        else:
            drift.append((k, a, b))
    if drift:
        print(f"\n  DRIFT in {title}:")
        for k, a, b in drift:
            print(f"    {k}\n        prod: {str(a)[:110]}\n        eval: {str(b)[:110]}")
    return drift


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--run-dir", required=True, help="directory holding prod.json and prod-bank.json")
    ap.add_argument("eval_bank", nargs="?", help="also compare this eval bank's config")
    args = ap.parse_args()
    print("== container environment")
    drift = report("container environment", prod_env(args.run_dir),
                   container_env(EVAL_CONTAINER), ENV_ALLOWED)
    if args.eval_bank:
        print("\n== bank config")
        drift += report("bank config", prod_bank_config(args.run_dir),
                        bank_config(EVAL_API, args.eval_bank), BANK_ALLOWED)
    if drift:
        print(f"\nFAIL: {len(drift)} unexplained difference(s). "
              f"The eval would measure this stack, not production's.")
        return 1
    print("\nPASS: eval stack matches production except where documented.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
