#!/usr/bin/env python3
"""Score one arm: how much literal code detail survived extraction.

Three things are measured, because any one of them alone can be gamed:

  survival   fraction of hard tokens that appear verbatim in the facts
             extracted from *that same* memory. Matched longest-first with the
             span consumed, so `--stdin` inside `--stdin-timeout` is not a
             second hit. Scoped per document, so another memory quoting the
             same path cannot lend it a hit.
  silent     memories that produced no facts at all. A retain reports success
             either way, so this is the loss that never shows up as an error.
  expansion  facts characters per source character. A model that copies the
             source wholesale scores 100% survival and is useless; a ratio far
             above the deepseek-v4-pro reference of 1.27 is that failure.
"""
import argparse, json, os, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(os.path.dirname(HERE), "corpus")
ROOT = "/v1/default"

# Occur inside ordinary prose, so a verbatim match proves nothing. A metric
# that silently rounds up is worse than no metric.
EXCLUDED = {"iat", "nbf", "exp", "throws", "notes"}


def get(base, path):
    with urllib.request.urlopen(base + path, timeout=120) as r:
        return json.loads(r.read())


def load_corpus(subset_file=None):
    keep = None
    if subset_file:
        with open(subset_file, encoding="utf-8") as fh:
            keep = {line.strip() for line in fh if line.strip()}
    out = []
    for name in sorted(os.listdir(CORPUS)):
        if name.endswith(".json") and name != "queries.json":
            payload = json.load(open(os.path.join(CORPUS, name), encoding="utf-8"))
            for m in payload["memories"]:
                if keep is not None and m["id"] not in keep:
                    continue
                m["stratum"] = payload["stratum"]
                out.append(m)
    if keep is not None and len(out) != len(keep):
        raise SystemExit(f"subset lists {len(keep)} ids but {len(out)} matched the corpus")
    return out


def fetch_facts(base, bank):
    by_doc, offset = {}, 0
    while True:
        page = get(base, f"{ROOT}/banks/{bank}/memories/list?limit=200&offset={offset}")
        items = page.get("items", [])
        for it in items:
            by_doc.setdefault(it.get("document_id"), []).append(it.get("text") or "")
        offset += len(items)
        if not items or offset >= page.get("total", 0):
            return by_doc


def scored_tokens(tokens):
    """The tokens a memory is actually graded on.

    A token that is a substring of a longer token in the same memory cannot be
    graded independently: `--stdin` inside `typer.Option(5.0, "--stdin-timeout"
    ...)` either free-rides on the long one (inflating the score) or, once the
    long match is consumed, is reported missing while sitting in plain sight
    (deflating it). 103 tokens in the corpus are nested this way, most of them
    in code_handover. Dropping them from the graded set is the only reading
    that is neither: the long token already proves whether that literal
    survived.
    """
    uniq = {t for t in tokens if t not in EXCLUDED}
    return sorted((t for t in uniq if not any(t != o and t in o for o in uniq)),
                  key=len, reverse=True)


def survived(tokens, haystack):
    """Longest first, consuming each match so a repeated token needs a repeat."""
    hits = []
    for t in scored_tokens(tokens):
        i = haystack.find(t)
        if i >= 0:
            hits.append(t)
            haystack = haystack[:i] + "\x00" * len(t) + haystack[i + len(t):]
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True, help="where score.json lands")
    ap.add_argument("--bank", required=True)
    ap.add_argument("--base-url", default="http://localhost:18888")
    ap.add_argument("--label", default="")
    ap.add_argument("--subset", default="", help="file of memory ids, one per line")
    ap.add_argument("--misses", type=int, default=0, help="print N longest missed tokens")
    args = ap.parse_args()

    memories = load_corpus(args.subset or None)
    by_doc = fetch_facts(args.base_url, args.bank)

    unattributed = len(by_doc.get(None, []))
    strata, rows, all_misses = {}, [], []
    for m in memories:
        facts = by_doc.get(m["id"], [])
        blob = "\n".join(facts)
        scored = scored_tokens(m["hard_tokens"])
        hits = survived(m["hard_tokens"], blob)
        misses = [t for t in scored if t not in hits]
        all_misses += [(len(t), t, m["id"]) for t in misses]
        s = strata.setdefault(m["stratum"], {"hit": 0, "tot": 0, "silent": 0,
                                             "src": 0, "fact": 0, "n": 0, "facts": 0})
        s["hit"] += len(hits); s["tot"] += len(scored); s["n"] += 1
        s["src"] += len(m["text"]); s["fact"] += len(blob); s["facts"] += len(facts)
        if not facts:
            s["silent"] += 1
        rows.append({"id": m["id"], "stratum": m["stratum"], "hits": len(hits),
                     "total": len(scored), "facts": len(facts), "missed": misses})

    label = args.label or args.bank
    print(f"\n  {label}")
    print(f"  {'stratum':<22}{'survival':>16}{'silent':>9}{'facts':>8}{'expand':>9}")
    T = {"hit": 0, "tot": 0, "silent": 0, "src": 0, "fact": 0, "facts": 0}
    for name in sorted(strata):
        s = strata[name]
        for k in T:
            T[k] += s[k]
        pct = 100.0 * s["hit"] / s["tot"] if s["tot"] else 0.0
        print(f"  {name:<22}{s['hit']:>6}/{s['tot']:<5}{pct:>6.1f}%"
              f"{s['silent']:>6}/{s['n']:<3}{s['facts']:>8}"
              f"{s['fact']/s['src'] if s['src'] else 0:>9.2f}")
    pooled = 100.0 * T["hit"] / T["tot"] if T["tot"] else 0.0
    print(f"  {'POOLED':<22}{T['hit']:>6}/{T['tot']:<5}{pooled:>6.1f}%"
          f"{T['silent']:>6}/{len(memories):<3}{T['facts']:>8}"
          f"{T['fact']/T['src'] if T['src'] else 0:>9.2f}")

    print(f"\n  {unattributed} observation facts carry no document_id and are not scored:"
          f" they are synthesised across memories, so crediting a token to one source"
          f" would be guesswork.")

    if args.misses:
        print(f"\n  longest missed tokens:")
        for _, t, mid in sorted(all_misses, reverse=True)[:args.misses]:
            print(f"    {mid:<26} {t!r}")

    out = os.path.join(args.run_dir, "score.json")
    json.dump({"bank": args.bank, "label": label, "pooled_pct": round(pooled, 1),
               "totals": T, "strata": strata, "memories": rows},
              open(out, "w", encoding="utf-8"), indent=2)
    print(f"\n  wrote {out}")


if __name__ == "__main__":
    sys.exit(main())
