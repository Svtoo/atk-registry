#!/usr/bin/env python3
"""Put the finished runs side by side, write side.

Every run with a score.json is a column, oldest first. --runs narrows to a
comma-separated list of run ids. Copy ratios read each run's facts back from
the eval instance, so its banks must still exist and it must be up.
"""
import argparse, difflib, os, statistics, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import runs, tally

ap = argparse.ArgumentParser()
ap.add_argument("--runs", help="comma-separated run ids; default is every run")
ap.add_argument("--base-url", default="http://localhost:18888")
args = ap.parse_args()

arms = []
for rid, path in runs.list_runs(runs.parse_only(args.runs)):
    score = runs.load(path, "score.json")
    if score is None:
        print(f"  skipping {rid}: no score.json")
        continue
    run = runs.load(path, "run.json")
    score["run_id"] = rid
    score["subset_ids"] = set(run["subset_ids"])
    score["ran_on"] = runs.stack(run)
    arms.append(score)
if not arms:
    sys.exit("no scored runs yet")

try:
    urllib.request.urlopen(f"{args.base_url}/health", timeout=10)
except Exception as e:
    sys.exit(f"eval instance not reachable at {args.base_url} ({e}); copy ratios read its banks. "
             f"Bring it up with 'model-eval read <run-id>' or 'docker start hindsight-eval'.")

names = [a["label"].split()[0] for a in arms]
STRATA = sorted(arms[0]["strata"])

print("\n  columns:")
for name, a in zip(names, arms):
    ran = a["ran_on"]
    strict = "" if ran["strict_schema"] in (None, True) else "  strict_schema=false"
    print(f"    {name:<14}{a['run_id']}  {ran['provider']} {ran['model']}"
          f"  ({len(a['memories'])} memories){strict}")

print(f"\n  {'':<22}" + "".join(f"{n:>14}" for n in names))
for s in STRATA:
    row = f"  {s:<22}"
    for a in arms:
        d = a["strata"].get(s, {})
        pct = 100 * d.get("hit", 0) / d["tot"] if d.get("tot") else 0
        row += f"{pct:>13.1f}%"
    print(row)
print(f"  {'-'*22}" + "".join("-" * 14 for _ in arms))
for label, fn in (
    ("POOLED survival", lambda a: f"{a['pooled_pct']:.1f}%"),
    ("silent losses",   lambda a: f"{a['totals']['silent']}/{len(a['memories'])}"),
    ("facts extracted", lambda a: str(a["totals"]["facts"])),
    ("expansion ratio", lambda a: f"{a['totals']['fact']/a['totals']['src']:.2f}"),
):
    print(f"  {label:<22}" + "".join(f"{fn(a):>14}" for a in arms))

# Survival on its own cannot rank models, because copying the source scores
# 100%. A model that quotes whole sentences beats one that genuinely extracts,
# on this metric, while producing longer and worse retrieval targets. So the
# ranking is only readable next to how much of each fact is lifted verbatim.
def copy_ratios(a):
    mems = {m["id"]: m for m in tally.load_corpus() if m["id"] in a["subset_ids"]}
    out = []
    for mid, facts in tally.fetch_facts(args.base_url, a["bank"]).items():
        if mid not in mems:
            continue
        src = mems[mid]["text"]
        for f in facts:
            if len(f) < 40:
                continue
            run = max((b.size for b in difflib.SequenceMatcher(
                None, f, src, autojunk=False).get_matching_blocks()), default=0)
            out.append(run / len(f))
    if not out:
        sys.exit(f"bank {a['bank']!r} holds no facts for run {a['run_id']}; was it deleted?")
    return out


print()
print(f"  {'':<22}" + "".join(f"{n:>14}" for n in names))
cr = {a["run_id"]: copy_ratios(a) for a in arms}
for label, fn in (
    ("median copied",  lambda r: f"{statistics.median(r):.0%}"),
    ("facts >60% copied", lambda r: f"{sum(1 for x in r if x > 0.6)/len(r):.0%}"),
):
    print(f"  {label:<22}" + "".join(f"{fn(cr[a['run_id']]):>14}" for a in arms))

# Same literals in fewer facts is not the same memory: fewer facts means fewer
# distinct retrieval targets, which this metric cannot see.
base = arms[0]
print(f"\n  facts scored here count only those attributable to a subset memory;"
      f"\n  observations carry no document_id and are excluded.")
print(f"  facts relative to {names[0]} ({base['run_id']}):")
for name, a in list(zip(names, arms))[1:]:
    delta = a["totals"]["facts"] / base["totals"]["facts"] - 1
    print(f"    {name:<14}{a['totals']['facts']:>5} facts  "
          f"({delta:+.0%} vs {base['totals']['facts']})")
