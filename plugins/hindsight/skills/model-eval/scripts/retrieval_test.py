#!/usr/bin/env python3
"""Tier 3: can the facts be found again?

Tier 1 and Tier 2 measure what an extractor wrote down. This measures the only
thing that matters afterwards: whether a future agent asking about a known fact
gets it back. It builds a fixed query set from the corpus ground truth, runs each
query against every arm's Hindsight bank, and computes recall@1/@5/@10 and MRR.

Query construction (deterministic, seeded)
------------------------------------------
Every query targets one specific known fact, identified by a hard token from the
corpus ground truth - `EXIT_STDIN_TIMEOUT = 65`, `typer.Option(...)`, a full path.
The query itself is the surrounding prose with every hard token of that sentence
stripped out, so the query cannot leak the answer string into BM25. A result
counts as a hit when its fact text carries the target token verbatim.

That is the point: an arm that dissolved `_stdin_prompt` into prose can still be
retrieved by the prose and still misses, because the identifier a future agent
needs is not in what came back.

Misses are split into two causes, which are different bugs:
  * not_in_arm_inventory      - the extractor never kept the token (Tier-1 loss)
  * in_inventory_not_retrieved - the fact exists in the bank but did not rank
                                 into the top k (retrieval/ranking loss)

Hindsight API (v0.9.x)
----------------------
  POST {base}/v1/{tenant}/banks/{bank}/memories/recall
  GET  {base}/v1/{tenant}/banks
  GET  {base}/health
Recall has no k parameter: it returns ranked facts until max_tokens is spent, so
--max-tokens bounds how deep recall@10 can even look. Queries returning fewer
than 10 results are counted and reported.

Usage
-----
  python3 retrieval_test.py --generate-only --subset ../corpus/half.txt --queries-out /tmp/queries.json
  python3 retrieval_test.py --arm x --arm-bank x=<bank> --out /tmp/retrieval.json

The frozen corpus/queries.json is this generator's output for half.txt with
the default seed; regenerating reproduces it byte for byte. read_test.py runs
the read side against that frozen set. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from evalcommon import (  # noqa: E402
    CORPUS_DIR,
    DEFAULT_BANK_TEMPLATE,
    EvalError,
    Hindsight,
    HttpError,
    Memory,
    Progress,
    fact_text,
    resolve_banks,
    die,
    http_json,
    load_corpus,
    load_extractions,
    mean,
    median,
    norm_ws,
    strip_code_fence,
    loose_contains,
    verbatim_contains,
    write_json_atomic,
)

DEFAULT_BASE_URL = "http://127.0.0.1:18888"
DEFAULT_TENANT = "default"
GENERATOR_VERSION = "hard-token-elision/1"

# --------------------------------------------------------------------------
# query construction
# --------------------------------------------------------------------------

# Deliberately not splitting on ':', because code artifacts carry colons
# (`_stdin_prompt(timeout: float = 5.0)`, `test_file.py::test_case`,
# `127.0.0.1:8787`) and a split mid-token would leak half the answer into a
# query, because elision can no longer match the token as a whole.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_PUNCT_RUN = re.compile(r"\s*([,;:.!?])\s*\1+")
_ORPHAN_PUNCT = re.compile(r"\s+([,;:.!?])")
_EMPTY_QUOTES = re.compile(r"``|\(\s*\)|\[\s*\]|\{\s*\}")


def split_sentences(text: str) -> list[str]:
    """Paragraph-aware sentence split. Good enough to locate a token's clause."""
    out: list[str] = []
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            continue
        out.extend(s.strip() for s in _SENTENCE_SPLIT.split(para) if s.strip())
    return out


def elide_tokens(sentence: str, tokens: list[str]) -> str:
    """Remove every hard token from a sentence, longest first, then tidy up.

    Longest-first matters: removing `--stdin-timeout` before `--stdin` stops a
    short token from carving a fragment out of a longer one.
    """
    text = sentence
    for tok in sorted({strip_code_fence(t) for t in tokens if strip_code_fence(t)}, key=len, reverse=True):
        text = text.replace(f"`{tok}`", " ")
        text = text.replace(tok, " ")
    text = _EMPTY_QUOTES.sub(" ", text).replace("`", " ")
    text = norm_ws(text)
    text = _PUNCT_RUN.sub(r"\1", text)
    text = _ORPHAN_PUNCT.sub(r"\1", text)
    return norm_ws(text.strip(" ,;:-"))


def scrub_partial_leaks(text: str, token: str, min_len: int = 6) -> str:
    """Delete any run of >= min_len characters of the target token from `text`.

    Whole-token elision is not enough on its own: a wrapped path, a token the
    source writes twice with different punctuation, or a fragment left by an
    earlier substitution can still hand the answer to BM25. This removes the
    longest surviving fragment until none is left.
    """
    tok = strip_code_fence(token)
    if len(tok) < min_len:
        return norm_ws(text)
    while True:
        best = ""
        for start in range(len(tok) - min_len + 1):
            for end in range(len(tok), start + min_len - 1, -1):
                sub = tok[start:end]
                if len(sub) <= len(best):
                    break
                if sub in text:
                    best = sub
                    break
        if not best:
            return norm_ws(text)
        text = text.replace(best, " ")


def informativeness(token: str) -> tuple[int, int]:
    """Rank candidate target tokens: structured identifiers before bare words."""
    tok = strip_code_fence(token)
    structured = 1 if re.search(r"[/_.()\-=:]|[a-z][A-Z]", tok) else 0
    return (structured, min(len(tok), 80))


def build_queries(
    corpus: dict[str, Memory],
    per_memory: int,
    seed: int,
    min_words: int = 6,
    max_words: int = 60,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build the fixed query set. Returns (queries, skipped_diagnostics)."""
    # Global token frequency: a token in exactly one memory makes an unambiguous
    # target, because any bank fact carrying it can only have come from there.
    freq: dict[str, int] = {}
    for mem in corpus.values():
        seen = {strip_code_fence(t) for t in mem.hard_tokens}
        for tok in seen:
            if tok:
                freq[tok] = freq.get(tok, 0) + 1

    queries: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for mem in corpus.values():
        sentences = split_sentences(mem.text)
        anchor = elide_tokens(sentences[0], list(mem.hard_tokens)) if sentences else ""
        anchor_words = anchor.split()[:12]
        anchor = " ".join(anchor_words)

        candidates = []
        for tok in mem.hard_tokens:
            clean = strip_code_fence(tok)
            if len(clean) < 3:
                skipped.append({"memory_id": mem.id, "token": tok, "reason": "token_too_short"})
                continue
            if not verbatim_contains(mem.text, clean):
                skipped.append({"memory_id": mem.id, "token": tok, "reason": "token_not_in_source_text"})
                continue
            candidates.append(clean)

        # Deterministic order: globally unique first, then structured identifiers,
        # then a seeded tiebreak so the set is stable but not corpus-order biased.
        rng = random.Random(f"{seed}:{mem.id}")
        decorated = []
        for tok in candidates:
            unique = freq.get(tok, 0) == 1
            decorated.append((0 if unique else 1, -informativeness(tok)[0], -informativeness(tok)[1],
                              rng.random(), tok, unique))
        decorated.sort()

        picked = 0
        for _, _, _, _, tok, unique in decorated:
            if picked >= per_memory:
                break
            idxs = [i for i, s in enumerate(sentences) if verbatim_contains(s, tok)]
            if not idxs:
                skipped.append({"memory_id": mem.id, "token": tok, "reason": "no_sentence_contains_token"})
                continue
            idx = idxs[0]
            body = scrub_partial_leaks(elide_tokens(sentences[idx], list(mem.hard_tokens)), tok)
            # Too little prose left once the identifiers are gone: widen to the
            # neighbouring sentences rather than shipping a two-word query.
            step = 1
            while len(body.split()) < min_words and step <= 2:
                lo, hi = max(0, idx - step), min(len(sentences), idx + step + 1)
                body = scrub_partial_leaks(
                    elide_tokens(" ".join(sentences[lo:hi]), list(mem.hard_tokens)), tok
                )
                step += 1
            if len(body.split()) < min_words:
                skipped.append({"memory_id": mem.id, "token": tok, "reason": "context_too_thin_after_elision"})
                continue

            # The anchor grounds the query in the note's subject, but only when
            # it adds something: widening can already have pulled it into body.
            head = " ".join(anchor.split()[:4])
            use_anchor = bool(anchor) and idx > 0 and head and head not in body
            text = f"{anchor}. {body}" if use_anchor else body
            text = scrub_partial_leaks(" ".join(text.split()[:max_words]), tok)
            text = _ORPHAN_PUNCT.sub(r"\1", _PUNCT_RUN.sub(r"\1", text)).strip(" ,;:-")
            if verbatim_contains(text, tok):
                skipped.append({"memory_id": mem.id, "token": tok, "reason": "target_leaked_into_query"})
                continue

            queries.append({
                "query_id": f"{mem.id}#q{picked + 1}",
                "memory_id": mem.id,
                "stratum": mem.stratum,
                "target_token": tok,
                "target_is_corpus_unique": unique,
                "source_sentence": sentences[idx],
                "query": text,
            })
            picked += 1

        if picked == 0:
            skipped.append({"memory_id": mem.id, "token": None, "reason": "no_usable_query_for_memory"})

    return queries, skipped


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------


def rank_of_hit(results: list[dict[str, Any]], token: str) -> tuple[int | None, int | None]:
    """1-based rank of the first verbatim hit, and of the first loose hit."""
    verbatim_rank = None
    loose_rank = None
    for i, res in enumerate(results, start=1):
        text = res.get("text") if isinstance(res, dict) else str(res)
        if not isinstance(text, str):
            continue
        if verbatim_rank is None and verbatim_contains(text, token):
            verbatim_rank = i
        if loose_rank is None and loose_contains(text, token):
            loose_rank = i
        if verbatim_rank is not None and loose_rank is not None:
            break
    return verbatim_rank, loose_rank


def run_query(hs: Hindsight, arm: str, bank: str, query: dict[str, Any],
              args: argparse.Namespace, seed: int) -> dict[str, Any]:
    rng = random.Random(f"{seed}:{arm}:{query['query_id']}")
    out: dict[str, Any] = {"arm": arm, "query_id": query["query_id"]}
    try:
        results, meta = hs.recall(
            bank=bank,
            query=query["query"],
            budget=args.budget,
            max_tokens=args.max_tokens,
            types=args.types or None,
            tags=args.tags or None,
            tags_match=args.tags_match,
            rng=rng,
        )
    except (EvalError, HttpError) as exc:
        out["error"] = str(exc)
        return out

    token = query["target_token"]
    rank, loose_rank = rank_of_hit(results, token)
    out.update({
        "n_results": len(results),
        "latency_s": meta.get("latency_s"),
        "first_hit_rank": rank,
        "first_loose_hit_rank": loose_rank,
        "reciprocal_rank": round(1.0 / rank, 4) if rank else 0.0,
    })
    if rank is None:
        out["top_result_preview"] = [
            norm_ws(str(r.get("text", "")))[:200] for r in results[:3] if isinstance(r, dict)
        ]
    return out


def summarise(queries: list[dict[str, Any]], per_query: dict[str, dict[str, Any]],
              arms: list[str], ks: tuple[int, ...]) -> dict[str, Any]:
    per_arm: dict[str, Any] = {}
    for arm in arms:
        rows = [per_query[q["query_id"]]["per_arm"][arm] for q in queries
                if arm in per_query.get(q["query_id"], {}).get("per_arm", {})]
        scored = [r for r in rows if "error" not in r]
        if not scored:
            per_arm[arm] = {"queries_scored": 0, "queries_failed": len(rows) - len(scored)}
            continue
        ranks = [r["first_hit_rank"] for r in scored]
        hits = [r for r in ranks if r]
        stratum_rows: dict[str, list[dict[str, Any]]] = {}
        for q in queries:
            row = per_query.get(q["query_id"], {}).get("per_arm", {}).get(arm)
            if row and "error" not in row:
                stratum_rows.setdefault(q["stratum"], []).append(row)

        def at_k(rs: list[dict[str, Any]], k: int) -> float:
            return round(sum(1 for r in rs if r["first_hit_rank"] and r["first_hit_rank"] <= k) / len(rs), 4)

        per_arm[arm] = {
            "queries_scored": len(scored),
            "queries_failed": len(rows) - len(scored),
            **{f"recall_at_{k}": at_k(scored, k) for k in ks},
            "mrr": round(sum(r["reciprocal_rank"] for r in scored) / len(scored), 4),
            "recall_at_%d_loose" % max(ks): round(
                sum(1 for r in scored
                    if r.get("first_loose_hit_rank") and r["first_loose_hit_rank"] <= max(ks)) / len(scored),
                4,
            ),
            "mean_first_hit_rank": mean(hits),
            "median_first_hit_rank": median(hits),
            "queries_with_no_hit": len(scored) - len(hits),
            "mean_results_returned": mean([r["n_results"] for r in scored]),
            "queries_returning_fewer_than_%d_results" % max(ks): sum(
                1 for r in scored if r["n_results"] < max(ks)
            ),
            "mean_latency_s": mean([r["latency_s"] for r in scored if r.get("latency_s")]),
            "miss_breakdown": _miss_breakdown(scored),
            "per_stratum": {
                stratum: {
                    **{f"recall_at_{k}": at_k(rs, k) for k in ks},
                    "mrr": round(sum(r["reciprocal_rank"] for r in rs) / len(rs), 4),
                    "queries": len(rs),
                }
                for stratum, rs in sorted(stratum_rows.items())
            },
        }
    return {"per_arm": per_arm}


def _miss_breakdown(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        if row["first_hit_rank"]:
            continue
        counts[row.get("miss_reason", "unknown_no_inventory")] = (
            counts.get(row.get("miss_reason", "unknown_no_inventory"), 0) + 1
        )
    return counts


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------


def resolve_arms_and_banks(args: argparse.Namespace) -> tuple[list[str], dict[str, str], Any]:
    extractions = None
    arms: list[str] = []
    if args.extractions and os.path.exists(args.extractions):
        try:
            extractions = load_extractions(args.extractions)
            arms = list(extractions.arms)
        except EvalError as exc:
            die(str(exc))
    elif args.extractions and not args.arm:
        die(f"extractions file not found: {args.extractions}",
            "Pass --arm NAME (repeatable) to run without it.")
    for arm in args.arm or []:
        if arm not in arms:
            arms.append(arm)
    if not arms:
        die("no arms to test", "Pass --extractions or --arm NAME.")

    banks = resolve_banks(arms, extractions, args.bank_template, args.arm_bank)
    return arms, banks, extractions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Tier 3: recall@k and MRR for each arm's memory bank.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--base-url", default=os.environ.get("HINDSIGHT_EVAL_URL", DEFAULT_BASE_URL))
    parser.add_argument("--tenant", default=DEFAULT_TENANT)
    parser.add_argument("--api-key-env", default="HINDSIGHT_API_KEY")
    parser.add_argument("--corpus-dir", default=CORPUS_DIR)
    parser.add_argument("--extractions", default=None,
                        help="Tier-1 output; supplies arm names and the inventory fallback")
    parser.add_argument("--arm", action="append", default=None,
                        help="arm name to test (repeatable); adds to those from --extractions")
    parser.add_argument("--arm-bank", action="append", default=None,
                        help="override an arm's bank as arm=bank (repeatable)")
    parser.add_argument("--bank-template", default=None,
                        help=f"bank name pattern, wins over the Tier-1 file's bank "
                             f"(default: {DEFAULT_BANK_TEMPLATE})")
    parser.add_argument("--out", default=None, help="result path; required unless --generate-only")
    parser.add_argument("--queries-per-memory", type=int, default=3)
    parser.add_argument("--subset", default="",
                        help="file of memory ids, one per line; must match what the arms were loaded with")
    parser.add_argument("--seed", type=int, default=20260824)
    parser.add_argument("--queries-in", default=None, help="reuse a frozen query set")
    parser.add_argument("--queries-out", default=None, help="also write the query set here")
    parser.add_argument("--generate-only", action="store_true",
                        help="build the query set and exit without calling Hindsight")
    parser.add_argument("--budget", choices=("low", "mid", "high"), default="mid")
    parser.add_argument("--max-tokens", type=int, default=4096,
                        help="recall token budget; caps how many facts can rank into top k")
    parser.add_argument("--types", action="append", default=None,
                        choices=("world", "experience", "observation"))
    parser.add_argument("--tags", action="append", default=None)
    parser.add_argument("--tags-match", default="any",
                        choices=("any", "all", "any_strict", "all_strict", "exact"))
    parser.add_argument("--k", default="1,5,10", help="comma-separated cutoffs")
    parser.add_argument("--inventory", choices=("auto", "api", "extractions", "none"), default="auto",
                        help="how to tell 'never extracted' from 'not retrieved'")
    parser.add_argument("--inventory-page-size", type=int, default=200)
    parser.add_argument("--inventory-max-pages", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0, help="use only the first N queries")
    parser.add_argument("--stratum", action="append", default=None)
    args = parser.parse_args(argv)

    ks = tuple(int(x) for x in args.k.split(",") if x.strip())
    if not ks:
        die("--k produced no cutoffs")

    try:
        corpus = load_corpus(args.corpus_dir, args.stratum, args.subset or None)
    except EvalError as exc:
        die(str(exc))

    if args.queries_in:
        with open(args.queries_in, encoding="utf-8") as fh:
            frozen = json.load(fh)
        queries = frozen["queries"] if isinstance(frozen, dict) else frozen
        skipped = frozen.get("skipped", []) if isinstance(frozen, dict) else []
        gen_meta = {"source": os.path.abspath(args.queries_in),
                    "generator": (frozen.get("generator") if isinstance(frozen, dict) else None)}
        if args.stratum:
            wanted = set(args.stratum)
            queries = [q for q in queries if q.get("stratum") in wanted]
    else:
        queries, skipped = build_queries(corpus, args.queries_per_memory, args.seed)
        gen_meta = {"source": "generated", "generator": GENERATOR_VERSION}
    if args.limit:
        queries = queries[: args.limit]
    if not queries:
        die("query set is empty", "check --queries-per-memory and the corpus hard_tokens")

    query_set_doc = {
        "generator": GENERATOR_VERSION,
        "seed": args.seed,
        "queries_per_memory": args.queries_per_memory,
        "n_queries": len(queries),
        "memories_covered": len({q["memory_id"] for q in queries}),
        "corpus_unique_targets": sum(1 for q in queries if q.get("target_is_corpus_unique")),
        "skipped": skipped,
        "queries": queries,
    }
    if args.queries_out:
        write_json_atomic(args.queries_out, query_set_doc)
        print(f"wrote query set to {args.queries_out}")

    if args.generate_only:
        print(f"generated {len(queries)} queries over "
              f"{query_set_doc['memories_covered']} memories "
              f"({query_set_doc['corpus_unique_targets']} corpus-unique targets); "
              f"{len(skipped)} candidates skipped")
        print("no retrieval was run; rerun without --generate-only", file=sys.stderr)
        return 0

    if not args.out:
        die("--out is required to run retrieval", "results never land inside the skill directory")
    arms, banks, extractions = resolve_arms_and_banks(args)
    hs = Hindsight(args.base_url, args.tenant, os.environ.get(args.api_key_env),
                   args.timeout, args.retries, page_size=args.inventory_page_size)
    try:
        health = hs.health()
        available = hs.banks()
    except EvalError as exc:
        die(str(exc))

    available_ids = set(available)
    missing = [f"{arm} -> {bank}" for arm, bank in banks.items() if bank not in available_ids]
    if missing:
        die(f"bank(s) not present on {args.base_url}: {', '.join(missing)}",
            f"available: {', '.join(sorted(str(b) for b in available_ids)) or '(none)'}. "
            "Fix --bank-template or --arm-bank, or run the retain pass first.")

    # Inventory: the difference between "the extractor lost it" and "recall
    # could not surface it". Whichever source is used is recorded, never assumed.
    inventories: dict[str, list[str]] = {}
    inventory_source: dict[str, str] = {}
    for arm in arms:
        if args.inventory == "none":
            inventory_source[arm] = "disabled"
            continue
        if args.inventory in ("auto", "api"):
            try:
                facts, note = hs.list_facts(banks[arm], args.inventory_max_pages)
                inventories[arm] = [fact_text(f) for f in facts if fact_text(f)]
                inventory_source[arm] = note
                continue
            except EvalError as exc:
                if args.inventory == "api":
                    die(f"bank inventory failed for {arm}: {exc}")
                print(f"note: bank inventory unavailable for {arm} ({exc}); "
                      "falling back to the extractions file", file=sys.stderr)
        if extractions is not None:
            texts = [t for per_arm in extractions.by_memory.values() for t in per_arm.get(arm, [])]
            inventories[arm] = texts
            inventory_source[arm] = f"{os.path.abspath(args.extractions)} ({len(texts)} facts)"
        else:
            inventory_source[arm] = "unavailable"

    print(f"running {len(queries)} queries x {len(arms)} arms against {args.base_url} "
          f"(budget={args.budget}, max_tokens={args.max_tokens})", file=sys.stderr)

    per_query: dict[str, dict[str, Any]] = {
        q["query_id"]: {**q, "per_arm": {}} for q in queries
    }
    jobs = [(arm, q) for q in queries for arm in arms]
    progress = Progress(len(jobs), "recall", enabled=sys.stderr.isatty())
    started = time.time()
    failures: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        futures = {
            pool.submit(run_query, hs, arm, banks[arm], q, args, args.seed): (arm, q)
            for arm, q in jobs
        }
        for fut in as_completed(futures):
            arm, q = futures[fut]
            try:
                row = fut.result()
            except Exception as exc:  # noqa: BLE001 - one query must not kill the run
                row = {"arm": arm, "query_id": q["query_id"],
                       "error": f"unhandled {type(exc).__name__}: {exc}"}
            if "error" in row:
                failures.append({"arm": arm, "query_id": q["query_id"], "error": row["error"]})
            elif row["first_hit_rank"] is None:
                token = q["target_token"]
                if arm in inventories:
                    in_bank = any(verbatim_contains(t, token) for t in inventories[arm])
                    row["miss_reason"] = ("in_inventory_not_retrieved" if in_bank
                                          else "not_in_arm_inventory")
                else:
                    row["miss_reason"] = "unknown_no_inventory"
            per_query[q["query_id"]]["per_arm"][arm] = row
            progress.tick(f"{arm} {q['query_id']}")
    progress.close()

    summary = summarise(queries, per_query, arms, ks)

    out_doc = {
        "schema_version": 1,
        "tier": 3,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "wall_seconds": round(time.time() - started, 1),
        "hindsight": {
            "base_url": args.base_url,
            "tenant": args.tenant,
            "recall_endpoint": f"/v1/{args.tenant}/banks/{{bank}}/memories/recall",
            "health": health,
            "banks": banks,
            "authenticated": bool(os.environ.get(args.api_key_env)),
        },
        "recall_params": {
            "budget": args.budget,
            "max_tokens": args.max_tokens,
            "types": args.types,
            "tags": args.tags,
            "tags_match": args.tags_match if args.tags else None,
            "k": list(ks),
            "note": (
                "Hindsight recall has no k parameter; it returns ranked facts until "
                "max_tokens is spent. recall@k is computed over the returned ranking, "
                "so a query returning fewer than max(k) results caps its own recall@k. "
                "Those queries are counted per arm."
            ),
        },
        "relevance_criterion": {
            "primary": "a returned fact whose text contains the target hard token verbatim "
                       "(whitespace-normalised, case-sensitive)",
            "diagnostic": "loose match ignores case and punctuation; reported as recall_at_"
                          f"{max(ks)}_loose",
            "rationale": "The query carries no hard token from its own sentence, so a hit "
                         "means the arm both kept the identifier and made it findable from "
                         "surrounding context.",
        },
        "arms": arms,
        "inventory_source": inventory_source,
        "query_set": {k: v for k, v in query_set_doc.items() if k != "queries"},
        "query_set_meta": gen_meta,
        "summary": summary,
        "failures": failures,
        "queries": queries,
        "per_query": [per_query[q["query_id"]] for q in queries],
    }
    write_json_atomic(args.out, out_doc)

    print(f"wrote {args.out}")
    for arm in arms:
        s = summary["per_arm"][arm]
        if not s.get("queries_scored"):
            print(f"  {arm:<28} no queries scored ({s.get('queries_failed', 0)} failed)")
            continue
        cuts = " ".join(f"r@{k}={s[f'recall_at_{k}']}" for k in ks)
        print(f"  {arm:<28} n={s['queries_scored']:<4} {cuts} mrr={s['mrr']} "
              f"misses={s['queries_with_no_hit']} {s['miss_breakdown']}")
    if failures:
        print(f"  {len(failures)} recall calls failed (see 'failures')", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
