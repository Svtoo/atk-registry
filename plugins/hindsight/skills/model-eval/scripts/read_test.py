#!/usr/bin/env python3
"""Everything on the read side, for ONE run, against the bank that run wrote.

The arm is a whole system: the model that ingested a bank is the model that
reads it. Splitting those apart measures a configuration nobody would deploy.
So this runs with the container already pointed at the run's own model, and
covers every path an agent actually uses to get a memory back:

  recall          hybrid search + rerank over the bank. Observations are left
                  in, because consolidation output is part of what comes back.
  reflect         synthesis over recalled facts. The literal either survives
                  into the answer or the agent never sees it.
  mental models   a standing synthesis at a fixed token budget. Scored as
                  distinct ground-truth literals carried per budget, since
                  that budget is context an agent pays for on every load.

Scoring reuses tally.py's rules so ingestion and retrieval never grade against
different token sets. The bank, the label and the memory subset come from the
run's run.json, so the read side cannot disagree with the ingest about what it
is reading; queries whose memory the run never ingested are left out.
"""
import argparse, json, os, sys, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import runs, tally

QUERIES = os.path.join(os.path.dirname(HERE), "corpus", "queries.json")
ROOT = "/v1/default"

MENTAL_MODELS = [
    ("eval-code", "Code artifacts on record",
     "What code artifacts are on record: file paths, CLI flags, function "
     "signatures, shell commands, error codes and identifiers? Quote each one "
     "exactly as written."),
    ("eval-decisions", "Decisions and rejected alternatives",
     "What decisions were made, which alternatives were rejected and why, and "
     "what were the measured numbers behind them? Keep every literal value."),
]


def api(base, method, path, body=None, timeout=600):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path} -> {e.code}: "
                           f"{e.read()[:300].decode(errors='replace')}")


def fact_types(base, bank):
    """Authoritative fact_type per id. The recall payload does not carry it, so
    the observation share can only be established by cross-referencing."""
    out, off = {}, 0
    while True:
        page = api(base, "GET", f"{ROOT}/banks/{bank}/memories/list?limit=200&offset={off}")
        items = page.get("items", [])
        for it in items:
            out[it["id"]] = it.get("fact_type")
        off += len(items)
        if not items or off >= page.get("total", 0):
            return out


# ---------------------------------------------------------------- recall
def run_recall(base, bank, queries, types_by_id, jobs, budget, max_tokens):
    def one(q):
        try:
            r = api(base, "POST", f"{ROOT}/banks/{bank}/memories/recall",
                    {"query": q["query"], "budget": budget, "max_tokens": max_tokens})
        except Exception as e:
            return {"query_id": q["query_id"], "error": str(e)[:200]}
        results = r.get("results", [])
        tok = q["target_token"]
        rank = next((i for i, x in enumerate(results, 1)
                     if tok in (x.get("text") or "")), None)
        obs = sum(1 for x in results if types_by_id.get(x.get("id")) == "observation")
        return {"query_id": q["query_id"], "stratum": q["stratum"],
                "memory_id": q["memory_id"], "rank": rank,
                "n_results": len(results), "n_observations": obs,
                # separates "the model never kept it" from "it is stored but did not rank"
                "in_bank": any(tok in (x.get("text") or "") for x in results) or None}
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        return list(pool.map(one, queries))


def inventory(base, bank, queries):
    """Which target tokens exist anywhere in the bank at all."""
    texts, off = [], 0
    while True:
        page = api(base, "GET", f"{ROOT}/banks/{bank}/memories/list?limit=200&offset={off}")
        items = page.get("items", [])
        texts += [it.get("text") or "" for it in items]
        off += len(items)
        if not items or off >= page.get("total", 0):
            break
    blob = "\n".join(texts)
    return {q["query_id"]: (q["target_token"] in blob) for q in queries}


# ---------------------------------------------------------------- reflect
def run_reflect(base, bank, questions, jobs, budget, max_tokens):
    def one(q):
        try:
            r = api(base, "POST", f"{ROOT}/banks/{bank}/reflect",
                    {"query": q["query"], "budget": budget, "max_tokens": max_tokens})
        except Exception as e:
            return {"query_id": q["query_id"], "error": str(e)[:200]}
        answer = r.get("text") or r.get("answer") or r.get("response") or ""
        if not answer:
            return {"query_id": q["query_id"], "error": f"no text in reflect response: {list(r)}"}
        u = r.get("usage") or {}
        return {"query_id": q["query_id"], "stratum": q["stratum"],
                "target_token": q["target_token"],
                "hit": q["target_token"] in answer,
                "answer_chars": len(answer),
                "input_tokens": u.get("input_tokens"), "output_tokens": u.get("output_tokens"),
                "answer": answer[:1200]}
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        return list(pool.map(one, questions))


# ---------------------------------------------------- mental models
def clear_mental_models(base, bank):
    """Start every arm with none.

    reflect includes mental models in its context by default, so an arm that
    already had them would answer from its own previous summaries while a fresh
    arm answered from raw facts. Since this script creates them, a re-run would
    silently give that arm an advantage no other arm had.
    """
    existing = api(base, "GET", f"{ROOT}/banks/{bank}/mental-models").get("items", [])
    for mm in existing:
        api(base, "DELETE", f"{ROOT}/banks/{bank}/mental-models/{mm['id']}")
    return [mm["id"] for mm in existing]


def run_mental_models(base, bank, all_tokens, wait_s=900):
    """Create, wait for the generation it starts, then read.

    Creating a mental model kicks off a generation of its own. Calling refresh
    straight after starts a second one, and the two race: whichever lands first
    is what a poller sees, and the other overwrites it afterwards. That is how
    the same model measured 24,956 chars during a run and 7,251 chars after it.
    So: create once, wait for that generation, verify the content has settled,
    and never refresh on top of it.
    """
    PLACEHOLDER = "Generating content..."
    rows = []
    for mm_id, name, source_query in MENTAL_MODELS:
        t_mm = time.time()
        api(base, "POST", f"{ROOT}/banks/{bank}/mental-models",
            {"id": mm_id, "name": name, "source_query": source_query,
             "max_tokens": 2048})

        content, deadline, ready = "", time.time() + wait_s, False
        while time.time() < deadline:
            time.sleep(10)
            got = api(base, "GET", f"{ROOT}/banks/{bank}/mental-models/{mm_id}?detail=content")
            content = (got.get("content") or "").strip()
            if content and content != PLACEHOLDER:
                ready = True
                break
        if not ready:
            rows.append({"id": mm_id, "error": f"still {content[:40]!r} after {wait_s}s",
                         "seconds": round(time.time() - t_mm, 1)})
            continue

        # Settled? A second read after a pause must agree, or the number is a
        # snapshot of something still moving and cannot be compared across arms.
        time.sleep(20)
        again = (api(base, "GET", f"{ROOT}/banks/{bank}/mental-models/{mm_id}?detail=content")
                 .get("content") or "").strip()
        stable = again == content
        if not stable:
            content = again

        hits = sorted({t for t in all_tokens if t in content}, key=len, reverse=True)
        rows.append({"id": mm_id, "chars": len(content), "tokens_carried": len(hits),
                     "seconds": round(time.time() - t_mm, 1),
                     "stable": stable, "sample_tokens": hits[:8],
                     "content": content[:1500]})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True,
                    help="directory holding run.json; read.json lands beside it")
    ap.add_argument("--base-url", default="http://localhost:18888")
    ap.add_argument("--queries", default=QUERIES)
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--reflect-per-stratum", type=int, default=5)
    ap.add_argument("--max-target-chars", type=int, default=65,
                    help="reflect targets longer than this are skipped as unfair to a summary")
    # The API's own default. Identical across arms either way; naming it keeps
    # the run reproducible rather than dependent on an unstated choice.
    ap.add_argument("--budget", default="low")
    ap.add_argument("--max-tokens", type=int, default=4096)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--skip-mental-models", action="store_true")
    ap.add_argument("--mental-models-only", action="store_true",
                    help="redo just the mental models, merging into the existing result")
    args = ap.parse_args()

    with open(os.path.join(args.run_dir, "run.json"), encoding="utf-8") as fh:
        run = json.load(fh)
    bank = run["bank"]
    label = f"{run['arm']}  {runs.stack(run)['model']}"
    keep = set(run["subset_ids"])
    path = os.path.join(args.run_dir, "read.json")

    queries = [q for q in json.load(open(args.queries))["queries"] if q["memory_id"] in keep]
    if not queries:
        sys.exit(f"FATAL: no query in {args.queries} targets a memory this run ingested")
    if args.limit:
        queries = queries[:args.limit]

    # Deterministic, stratum-balanced reflect subset: reflect is the expensive
    # path, and an unbalanced sample would let one stratum decide the number.
    by_stratum = {}
    for q in queries:
        # An atomic literal - a flag, a path, an id, a number - is something a
        # summary can reasonably be required to carry. A full signature is not:
        # reflect condenses, so requiring it verbatim scores every model zero
        # and measures nothing.
        if len(q["target_token"]) > args.max_target_chars:
            continue
        by_stratum.setdefault(q["stratum"], []).append(q)
    reflect_qs = [q for s in sorted(by_stratum)
                  for q in by_stratum[s][:args.reflect_per_stratum]]

    mems = [m for m in tally.load_corpus() if m["id"] in keep]
    if len(mems) != len(keep):
        sys.exit(f"FATAL: run.json lists {len(keep)} memory ids but {len(mems)} matched the corpus")
    all_tokens = sorted({t for m in mems for t in tally.scored_tokens(m["hard_tokens"])},
                        key=len, reverse=True)

    print(f"  {label}  bank={bank}")
    print(f"  recall queries={len(queries)}  reflect questions={len(reflect_qs)}  "
          f"mental models={0 if args.skip_mental_models else len(MENTAL_MODELS)}")

    if args.mental_models_only:
        prev = json.load(open(path))
        clear_mental_models(args.base_url, bank)
        prev["mental_models"] = run_mental_models(args.base_url, bank, all_tokens)
        json.dump(prev, open(path, "w"), indent=1)
        for r in prev["mental_models"]:
            if "error" in r:
                print(f"  mental model {r['id']}: ERROR {r['error']}")
            else:
                print(f"  mental model {r['id']}: {r['tokens_carried']} literals in "
                      f"{r['chars']} chars  {r['seconds']}s  stable={r['stable']}")
        print(f"  updated {path}")
        return 0

    cleared = clear_mental_models(args.base_url, bank)
    if cleared:
        print(f"  cleared {len(cleared)} pre-existing mental model(s): {cleared} "
              f"so reflect answers from facts, as it does for every other arm")

    t0 = time.time()
    types_by_id = fact_types(args.base_url, bank)
    inv = inventory(args.base_url, bank, queries)
    rec = run_recall(args.base_url, bank, queries, types_by_id,
                     args.jobs, args.budget, args.max_tokens)
    t_rec = time.time() - t0
    print(f"  recall done in {t_rec/60:.1f} min")

    t1 = time.time()
    ref = run_reflect(args.base_url, bank, reflect_qs, args.jobs,
                      args.budget, args.max_tokens)
    t_ref = time.time() - t1
    print(f"  reflect done in {t_ref/60:.1f} min")

    mm = [] if args.skip_mental_models else run_mental_models(args.base_url, bank, all_tokens)

    ok = [r for r in rec if "error" not in r]
    def at_k(k):
        return sum(1 for r in ok if r["rank"] and r["rank"] <= k) / len(ok) if ok else 0.0
    mrr = sum(1.0 / r["rank"] for r in ok if r["rank"]) / len(ok) if ok else 0.0
    missed = [r for r in ok if not r["rank"]]
    never_stored = [r for r in missed if not inv.get(r["query_id"])]
    obs_share = (sum(r["n_observations"] for r in ok) /
                 max(sum(r["n_results"] for r in ok), 1))
    ref_ok = [r for r in ref if "error" not in r]
    ref_hit = sum(1 for r in ref_ok if r["hit"]) / len(ref_ok) if ref_ok else 0.0

    out = {
        "run_id": run["run_id"], "label": label, "bank": bank,
        "recall": {"n": len(ok), "errors": len(rec) - len(ok),
                   "at1": at_k(1), "at5": at_k(5), "at10": at_k(10), "mrr": mrr,
                   "missed": len(missed), "missed_never_stored": len(never_stored),
                   "missed_stored_not_ranked": len(missed) - len(never_stored),
                   "observation_share_of_results": obs_share,
                   "mean_results": sum(r["n_results"] for r in ok) / max(len(ok), 1),
                   "minutes": round(t_rec / 60, 1), "per_query": rec},
        "reflect": {"n": len(ref_ok), "errors": len(ref) - len(ref_ok),
                    "literal_hit_rate": ref_hit,
                    "mean_answer_chars": sum(r["answer_chars"] for r in ref_ok) / max(len(ref_ok), 1),
                    "total_input_tokens": sum(r.get("input_tokens") or 0 for r in ref_ok),
                    "total_output_tokens": sum(r.get("output_tokens") or 0 for r in ref_ok),
                    "minutes": round(t_ref / 60, 1), "per_question": ref},
        "mental_models": mm,
    }
    json.dump(out, open(path, "w"), indent=1)

    print(f"  recall  @1={at_k(1):.1%} @5={at_k(5):.1%} @10={at_k(10):.1%} mrr={mrr:.3f}  "
          f"obs_share={obs_share:.0%}")
    print(f"  misses  {len(missed)} total = {len(never_stored)} never stored + "
          f"{len(missed)-len(never_stored)} stored but unranked")
    print(f"  reflect literal hit {ref_hit:.1%} over {len(ref_ok)} questions, "
          f"mean answer {out['reflect']['mean_answer_chars']:.0f} chars")
    for r in mm:
        if "error" in r:
            print(f"  mental model {r['id']}: ERROR {r['error']}")
        else:
            print(f"  mental model {r['id']}: {r['tokens_carried']} literals in {r['chars']} chars")
    print(f"  wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
