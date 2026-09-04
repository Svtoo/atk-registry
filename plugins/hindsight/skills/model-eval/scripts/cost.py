#!/usr/bin/env python3
"""Real cost and latency per run, from Hindsight's own LLM request log.

Every LLM call Hindsight makes is recorded with its operation, model, duration
and token counts, so this reports measured numbers rather than estimates. Cost
is computed from those measured tokens against live OpenRouter prices for the
hosts the run was pinned to, with cached input priced separately because the
cache-read rate is roughly a tenth of the prompt rate and ignoring it would
overstate the bill. The log covers everything the bank has done: ingest, and
the read side once it has run.

OpenRouter runs only, priced with the plugin's own key, which therefore has to
be an OpenRouter key: a run on any other provider has no OpenRouter endpoint
to price against and stops this script with a message.

Each run's figures are written to cost.json beside its run.json.
"""
import argparse, json, os, statistics, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import runs


def key():
    provider = os.environ.get("HINDSIGHT_LLM_PROVIDER")
    if provider != "openrouter":
        sys.exit(f"cost prices OpenRouter endpoints with the plugin key, and the plugin key is for "
                 f"{provider!r}; only an openrouter production can run it")
    k = os.environ.get("HINDSIGHT_LLM_API_KEY")
    if not k:
        sys.exit("HINDSIGHT_LLM_API_KEY is not set in the plugin environment")
    return k


def prices(model, pin, k):
    """Cheapest pinned endpoint's prices: the run routed within its pin, and
    the cheapest member is the closest single defensible basis."""
    req = urllib.request.Request(f"https://openrouter.ai/api/v1/models/{model}/endpoints",
                                 headers={"Authorization": f"Bearer {k}"})
    eps = json.load(urllib.request.urlopen(req, timeout=60))["data"]["endpoints"]
    inpin = [e for e in eps if e.get("tag") in pin] or eps
    e = min(inpin, key=lambda x: float(x["pricing"].get("prompt") or 9))
    p = e["pricing"]
    return (float(p.get("prompt") or 0), float(p.get("completion") or 0),
            float(p.get("input_cache_read") or p.get("prompt") or 0), e.get("tag"))


def requests_for(base, bank):
    out, off = [], 0
    while True:
        d = json.load(urllib.request.urlopen(
            f"{base}/v1/default/banks/{bank}/llm-requests?limit=200&offset={off}", timeout=180))
        it = d.get("items", [])
        out += it
        off += len(it)
        if not it or off >= d.get("total", 0):
            return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", help="comma-separated run ids; default is every run")
    ap.add_argument("--base-url", default="http://localhost:18888")
    args = ap.parse_args()
    k = key()

    selected = []
    for rid, path in runs.list_runs(runs.parse_only(args.runs)):
        run = runs.load(path, "run.json")
        ran = runs.stack(run)
        if ran["provider"] != "openrouter":
            sys.exit(f"run {rid} ran on {ran['provider']!r}; cost prices OpenRouter endpoints only. "
                     f"Narrow the selection with --runs.")
        selected.append((rid, path, run["arm"], run["bank"], ran["model"], ran["pin"] or []))

    print(f"\n  {'arm':<12}{'calls':>7}{'input':>12}{'cached':>11}{'output':>10}"
          f"{'$ total':>10}{'p50 s':>8}{'p90 s':>8}  run")
    totals = {}
    for rid, path, arm, bank, model, pin in selected:
        pp, cp, cachep, tag = prices(model, pin, k)
        reqs = requests_for(args.base_url, bank)
        ok = [r for r in reqs if r.get("status") == "success"]
        i = sum(r.get("input_tokens") or 0 for r in ok)
        c = sum(r.get("cached_tokens") or 0 for r in ok)
        o = sum(r.get("output_tokens") or 0 for r in ok)
        cost = (i - c) * pp + c * cachep + o * cp
        d = sorted((r.get("duration_ms") or 0) / 1000 for r in ok)
        p50 = statistics.median(d) if d else 0
        p90 = d[int(.9 * len(d))] if d else 0
        totals[rid] = {"arm": arm, "model": model, "calls": len(ok), "input": i, "cached": c,
                       "output": o, "cost": cost, "p50": p50, "p90": p90, "host": tag,
                       "price_in": pp * 1e6, "price_out": cp * 1e6}
        print(f"  {arm:<12}{len(ok):>7}{i:>12,}{c:>11,}{o:>10,}{cost:>10.2f}{p50:>8.1f}{p90:>8.1f}  {rid}")
        with open(os.path.join(path, "cost.json"), "w", encoding="utf-8") as fh:
            json.dump(totals[rid], fh, indent=1)

    print(f"\n  {'arm':<12}{'priced host':<20}{'$/M in':>9}{'$/M out':>10}")
    for rid, t in totals.items():
        print(f"  {t['arm']:<12}{str(t['host']):<20}{t['price_in']:>9.3f}{t['price_out']:>10.3f}")

    print(f"\n  latency by operation (p50 seconds)")
    ops = set()
    per = {}
    for rid, path, arm, bank, model, pin in selected:
        per[rid] = {}
        for r in requests_for(args.base_url, bank):
            if r.get("status") != "success":
                continue
            op = r.get("operation") or r.get("scope") or "?"
            ops.add(op)
            per[rid].setdefault(op, []).append((r.get("duration_ms") or 0) / 1000)
    print(f"  {'operation':<28}" + "".join(f"{s[2]:>12}" for s in selected))
    for op in sorted(ops):
        row = f"  {op:<28}"
        for rid, *_ in selected:
            v = per[rid].get(op)
            row += f"{statistics.median(v):>12.1f}" if v else f"{'-':>12}"
        print(row)
    print(f"\n  wrote cost.json into {len(totals)} run director{'y' if len(totals) == 1 else 'ies'}")


if __name__ == "__main__":
    sys.exit(main())
