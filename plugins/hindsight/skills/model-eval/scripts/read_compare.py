#!/usr/bin/env python3
"""Read-side results side by side, each bank read by the model that wrote it.

Every run with a read.json is a column, oldest first. --runs narrows to a
comma-separated list of run ids.
"""
import argparse, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import runs

ap = argparse.ArgumentParser()
ap.add_argument("--runs", help="comma-separated run ids; default is every run")
args = ap.parse_args()

arms = []
for rid, path in runs.list_runs(runs.parse_only(args.runs)):
    read = runs.load(path, "read.json")
    if read is None:
        print(f"  skipping {rid}: no read.json")
        continue
    read["run_id"] = rid
    read["ran_on"] = runs.stack(runs.load(path, "run.json"))
    arms.append(read)
if not arms:
    sys.exit("no read results yet")

names = [a["label"].split()[0] for a in arms]
print("\n  columns:")
for name, a in zip(names, arms):
    ran = a["ran_on"]
    print(f"    {name:<14}{a['run_id']}  {ran['provider']} {ran['model']}")
print(f"\n  {'':<26}" + "".join(f"{n:>14}" for n in names))

def row(label, fn):
    print(f"  {label:<26}" + "".join(f"{fn(a):>14}" for a in arms))

print("  -- recall (search + rerank, observations included) --")
row("queries",             lambda a: str(a['recall']['n']))
row("recall@1",            lambda a: f"{a['recall']['at1']:.1%}")
row("recall@5",            lambda a: f"{a['recall']['at5']:.1%}")
row("recall@10",           lambda a: f"{a['recall']['at10']:.1%}")
row("MRR",                 lambda a: f"{a['recall']['mrr']:.3f}")
row("observation share",   lambda a: f"{a['recall']['observation_share_of_results']:.0%}")
row("mean results/query",  lambda a: f"{a['recall']['mean_results']:.0f}")
print("  -- where the misses come from --")
row("missed",              lambda a: str(a['recall']['missed']))
row("  never stored",      lambda a: str(a['recall']['missed_never_stored']))
row("  stored, unranked",  lambda a: str(a['recall']['missed_stored_not_ranked']))
print("  -- reflect (synthesis, each by its own model) --")
row("questions",           lambda a: str(a['reflect']['n']))
row("literal hit rate",    lambda a: f"{a['reflect']['literal_hit_rate']:.1%}")
row("mean answer chars",   lambda a: f"{a['reflect']['mean_answer_chars']:.0f}")
row("input tokens",        lambda a: f"{a['reflect'].get('total_input_tokens', 0):,}")
print("  -- mental models (standing synthesis) --")
for mm_id in ("eval-code", "eval-decisions"):
    def get(a, key, mm_id=mm_id):
        m = next((x for x in a["mental_models"] if x.get("id") == mm_id), None)
        if not m or "error" in m:
            return "ERROR"
        return m[key]
    row(f"{mm_id}: literals",  lambda a: str(get(a, "tokens_carried")))
    row(f"{mm_id}: chars",     lambda a: f"{get(a,'chars'):,}" if isinstance(get(a,'chars'), int) else "ERROR")
    row(f"{mm_id}: per 1k ch", lambda a: (
        f"{1000*get(a,'tokens_carried')/get(a,'chars'):.1f}"
        if isinstance(get(a, "chars"), int) and get(a, "chars") else "ERROR"))

print("\n  Notes")
print("  - recall misses split into ingestion loss (never stored) and ranking")
print("    loss (stored but outside top 10). They are different problems.")
print("  - mental model max_tokens is 2048 for every arm, but content length")
print("    varies well beyond it, so literals-per-1k-chars is the density that")
print("    matters: that content is context an agent pays for on every load.")
print("  - columns with different query counts ran on different subsets and")
print("    are not comparable to each other.")
