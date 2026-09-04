"""Where runs live and how the compare scripts find them.

A run is a directory named <YYYY-MM-DD>_<arm>_<image-tag> under the plugin's
custom/ area, holding run.json (ingest), score.json (tally), read.json (read),
the production snapshot (prod.json, prod-bank.json) and the compose file and
pin it ran with. Directory order is date order.

The directory is not named after the entry script: `atk run` resolves a script
name through custom/<name> first, so a custom/model-eval directory would
shadow model-eval.sh.

    python3 runs.py --list
    python3 runs.py --export <run-id>     # shell assignments, for eval
"""
import json
import os
import shlex
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# Found through ATK's home, not by walking out of this skill; model-eval.sh
# exports both so every step of a run agrees on them.
PLUGIN_DIR = os.environ.get("HINDSIGHT_PLUGIN_DIR") or os.path.join(
    os.environ.get("ATK_HOME") or os.path.expanduser("~/.atk"),
    "plugins", "hindsight")
RUNS_DIR = os.environ.get("MODEL_EVAL_RUNS_DIR") or os.path.join(
    PLUGIN_DIR, "custom", "model-eval-runs")

STACK_FIELDS = ("provider", "model", "base_url", "pin", "strict_schema", "max_concurrent", "exclusive")


def list_runs(only=None, runs_dir=RUNS_DIR):
    """(run_id, path) for every run holding a run.json, oldest first.

    `only` restricts the list to those run ids and fails on one that does not
    exist: a typo must not silently narrow a comparison.
    """
    if not os.path.isdir(runs_dir):
        sys.exit(f"no runs directory at {runs_dir}; run an ingest first")
    ids = sorted(d for d in os.listdir(runs_dir)
                 if os.path.isfile(os.path.join(runs_dir, d, "run.json")))
    if only:
        unknown = [r for r in only if r not in ids]
        if unknown:
            sys.exit(f"unknown run(s) {unknown}; known: {ids}")
        ids = [r for r in ids if r in set(only)]
    return [(rid, os.path.join(runs_dir, rid)) for rid in ids]


def load(path, name):
    """One JSON artifact of a run, or None when that step has not run."""
    full = os.path.join(path, name)
    if not os.path.exists(full):
        return None
    with open(full, encoding="utf-8") as fh:
        return json.load(fh)


def stack(run):
    """What a run ran on, as a dict of STACK_FIELDS.

    A run.json written before these were recorded at top level carries only
    provider, model and extra_body under "stack", plus pin. Its base_url,
    strict_schema and max_concurrent come back as None; exclusive is False,
    since no run could stop production before the flag existed.
    """
    if "provider" in run:
        return {field: run.get(field) for field in STACK_FIELDS}
    legacy = run["stack"]
    return {"provider": legacy["provider"], "model": legacy["model"], "base_url": None,
            "pin": run.get("pin"), "strict_schema": None, "max_concurrent": None,
            "exclusive": False}


def parse_only(value):
    """--runs a,b,c as a list, or None for all runs."""
    if not value:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


def _list():
    rows = list_runs()
    if not rows:
        print(f"== no runs yet in {RUNS_DIR}")
        return 0
    print(f"  {'run':<34}{'arm':<12}{'provider':<12}{'model':<28}{'memories':>9}  {'drained':<8}{'steps'}")
    for rid, path in rows:
        run = load(path, "run.json")
        ran = stack(run)
        steps = " ".join(s for s in ("score", "read", "cost") if os.path.exists(os.path.join(path, s + ".json")))
        flags = " excl" if ran["exclusive"] else ""
        print(f"  {rid:<34}{run['arm']:<12}{ran['provider']:<12}{ran['model']:<28}{run['submitted']:>9}  "
              f"{str(run['drained']).lower():<8}{steps}{flags}")
    print(f"\n  in {RUNS_DIR}")
    return 0


def _export(run_id):
    """Shell assignments for the dispatcher to eval. None becomes the empty
    string; the pin is JSON."""
    path = os.path.join(RUNS_DIR, run_id)
    run = load(path, "run.json")
    if run is None:
        sys.exit(f"no run.json in {path}")
    ran = stack(run)
    pairs = [
        ("RUN_PROVIDER", ran["provider"]),
        ("RUN_MODEL", ran["model"]),
        ("RUN_BASE_URL", ran["base_url"] or ""),
        ("RUN_PIN", json.dumps(ran["pin"]) if ran["pin"] else ""),
        ("RUN_STRICT_SCHEMA", "" if ran["strict_schema"] is None else str(ran["strict_schema"]).lower()),
        ("RUN_MAX_CONCURRENT", "" if ran["max_concurrent"] is None else str(ran["max_concurrent"])),
        ("RUN_EXCLUSIVE", "true" if ran["exclusive"] else "false"),
        ("RUN_BANK", run["bank"]),
        ("RUN_IMAGE", run["image"]),
    ]
    print("\n".join(f"{name}={shlex.quote(value)}" for name, value in pairs))
    return 0


def main(argv):
    if len(argv) >= 2 and argv[1] == "--list":
        return _list()
    if len(argv) >= 3 and argv[1] == "--export":
        return _export(argv[2])
    print(__doc__, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
