#!/usr/bin/env python3
"""Run one eval arm: configure the bank, submit the corpus, wait for the queue.

The container serves one extraction model at a time, so an arm is
(restart the stack with a model) -> (this script) -> (tally.py).

Every arm must extract under byte-identical settings, otherwise the arms
measure the extraction config rather than the model. That is enforced here:
the bank config is written and then read back, and a mismatch is fatal.
"""
import argparse, json, os, sys, time, urllib.error, urllib.request

import evalcommon
import parity
import snapshot
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(os.path.dirname(HERE), "corpus")
ROOT = "/v1/default"
STACK_VARS = ("EVAL_LLM_PROVIDER", "EVAL_LLM_MODEL", "EVAL_LLM_BASE_URL", "EVAL_LLM_EXTRA_BODY",
              "EVAL_LLM_STRICT_SCHEMA", "EVAL_LLM_MAX_CONCURRENT")


def die(msg, hint=""):
    print(f"FATAL: {msg}", file=sys.stderr)
    if hint:
        print(f"       {hint}", file=sys.stderr)
    sys.exit(1)


def api(base, method, path, body=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path} -> {e.code}: {e.read()[:400].decode(errors='replace')}")


def load_corpus(subset_file=None):
    keep = None
    if subset_file:
        with open(subset_file, encoding="utf-8") as fh:
            keep = {line.strip() for line in fh if line.strip()}
    out = []
    for name in sorted(os.listdir(CORPUS)):
        if not name.endswith(".json") or name == "queries.json":
            continue
        stratum = name[:-5]
        with open(os.path.join(CORPUS, name), encoding="utf-8") as fh:
            payload = json.load(fh)
        items = payload["memories"] if isinstance(payload, dict) else payload
        for m in items:
            if keep is not None and m["id"] not in keep:
                continue
            m["stratum"] = stratum
            out.append(m)
    if keep is not None and len(out) != len(keep):
        die(f"subset lists {len(keep)} ids but {len(out)} matched the corpus")
    return out


def wait_writable(base, bank, timeout=300):
    """/health/ready goes green before the API accepts writes; stats does not."""
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            api(base, "GET", f"{ROOT}/banks/{bank}/stats", timeout=10)
            return
        except Exception as e:
            last = str(e)[:120]
        time.sleep(3)
    die(f"bank stats never responded within {timeout}s", last)


def configure(base, bank, instructions, run_dir):
    """Make the eval bank a copy of the production bank.

    Hand-picking settings here is how the first attempt ended up measuring
    extraction with observations and consolidation switched off while
    production runs both. So the settings are copied from the production bank
    as ingest snapshotted it rather than chosen, and read back to prove they
    took.
    """
    prod = parity.prod_bank_config(run_dir)
    if prod.get("retain_extraction_mode") != "custom":
        die(f"production bank is on retain_extraction_mode="
            f"{prod.get('retain_extraction_mode')!r}, expected 'custom'",
            "the eval copies production; fix production first")
    if (prod.get("retain_custom_instructions") or "").strip() != instructions.strip():
        die("production's retain instructions differ from the plugin's retain-instructions.md",
            "the arms must extract against the instructions production actually uses")

    api(base, "PUT", f"{ROOT}/banks/{bank}", {})
    updates = {k: prod.get(k) for k in parity.BANK_COPIED}
    api(base, "PATCH", f"{ROOT}/banks/{bank}/config", {"updates": updates})

    applied = api(base, "GET", f"{ROOT}/banks/{bank}/config").get("config", {})
    bad = [k for k in parity.BANK_COPIED if applied.get(k) != prod.get(k)]
    if bad:
        die(f"bank {bank!r} did not take {len(bad)} setting(s) from production: {bad}")
    return applied


def submit(base, bank, memories, jobs):
    """One retain per memory. A batch of N is a single serial task server-side,
    so batching turns a 20-minute arm into a 3-hour one."""
    def one(m):
        body = {"async": True, "items": [{
            "content": m["text"],
            "context": "eval",
            "document_id": m["id"],
            "update_mode": "replace",
        }]}
        try:
            api(base, "POST", f"{ROOT}/banks/{bank}/memories", body, timeout=60)
            return None
        except Exception as e:
            return (m["id"], str(e)[:200])

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        return [r for r in pool.map(one, memories) if r]


def op_total(base, bank):
    stats = api(base, "GET", f"{ROOT}/banks/{bank}/stats")
    return sum((stats.get("operations_by_status") or {}).values()), stats


def drain(base, bank, expected, baseline, timeout=3600, interval=5.0):
    """Wait for the queue.

    The naive "wait until nothing is in flight" is wrong twice over. A retain
    POST returns before its operations appear in stats - measured at ~8s - so
    the queue reads empty right after submitting. And any operation already in
    the bank makes a "has the queue ever been busy?" guard true immediately.
    So the gate is growth against the count taken before submitting: at least
    one new operation per memory must be visible before a zero counts.
    """
    started = time.time()
    armed = busy_since_arming = False
    quiet = 0
    stats = {}
    while time.time() - started < timeout:
        total, stats = op_total(base, bank)
        by = stats.get("operations_by_status") or {}
        inflight = sum(v for k, v in by.items() if k in ("pending", "processing", "queued", "running"))
        if not armed and total >= baseline + expected:
            armed = True
        if armed and inflight > 0:
            busy_since_arming = True
        if armed and busy_since_arming and inflight == 0:
            quiet += 1
            if quiet >= 2:
                return True, stats
        else:
            quiet = 0
            print(f"    {int(time.time()-started):>4}s  {'armed' if busy_since_arming else 'ARMING'} "
                  f"inflight={inflight:<4} new_ops={total-baseline}/{expected} "
                  f"docs={stats.get('total_documents')} "
                  f"facts={stats.get('total_nodes')}", flush=True)
        time.sleep(interval)
    return False, stats


def stack_from_env():
    """The stack the dispatcher exported for this run, as run.json records it."""
    missing = [name for name in STACK_VARS if os.environ.get(name) is None]
    if missing:
        die(f"the dispatcher did not export {missing}")
    env = {name: os.environ[name] for name in STACK_VARS}
    pin = None
    if env["EVAL_LLM_EXTRA_BODY"] != "null":
        try:
            pin = json.loads(env["EVAL_LLM_EXTRA_BODY"])["provider"]["only"]
        except (ValueError, KeyError, TypeError) as e:
            die(f"EVAL_LLM_EXTRA_BODY carries no provider.only pin: {e}")
    if env["EVAL_LLM_STRICT_SCHEMA"] not in ("true", "false"):
        die(f"EVAL_LLM_STRICT_SCHEMA must be true or false, got {env['EVAL_LLM_STRICT_SCHEMA']!r}")
    return {
        "provider": env["EVAL_LLM_PROVIDER"],
        "model": env["EVAL_LLM_MODEL"],
        "base_url": env["EVAL_LLM_BASE_URL"],
        "pin": pin,
        "strict_schema": env["EVAL_LLM_STRICT_SCHEMA"] == "true",
        "max_concurrent": int(env["EVAL_LLM_MAX_CONCURRENT"]),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True, help="where run.json lands; holds the production snapshot")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--arm", required=True)
    ap.add_argument("--image", required=True, help="the image production runs, and so the eval")
    ap.add_argument("--bank", required=True)
    ap.add_argument("--base-url", default="http://localhost:18888")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--subset", default="", help="file of memory ids, one per line")
    ap.add_argument("--exclusive", action="store_true",
                    help="record that production was stopped for this run")
    ap.add_argument("--wait-only", action="store_true",
                    help="attach to a run already in flight: drain and report, submit nothing")
    ap.add_argument("--drain-timeout", type=int, default=3600)
    args = ap.parse_args()

    instructions = evalcommon.retain_instructions()

    memories = load_corpus(args.subset or None)
    if args.limit:
        memories = memories[:args.limit]

    print(f"  bank={args.bank}  memories={len(memories)}  jobs={args.jobs}")
    wait_writable(args.base_url, args.bank)
    applied = configure(args.base_url, args.bank, instructions, args.run_dir)
    print(f"  bank copied from production: mode={applied['retain_extraction_mode']!r} "
          f"consolidation={applied['enable_auto_consolidation']} "
          f"observations={applied['enable_observations']} "
          f"chunk={applied['retain_chunk_size']}")

    ran = stack_from_env()
    print(f"  stack: {ran}  exclusive={args.exclusive}")

    t0 = time.time()
    if args.wait_only:
        errors, baseline = [], 0
        print("  --wait-only: attaching to work already in flight")
    else:
        baseline, _ = op_total(args.base_url, args.bank)
        errors = submit(args.base_url, args.bank, memories, args.jobs)
        print(f"  submitted {len(memories) - len(errors)}/{len(memories)} "
              f"in {time.time()-t0:.0f}s (ops before submit: {baseline})")
        for mid, err in errors[:10]:
            print(f"    SUBMIT FAILED {mid}: {err}")

    ok, stats = drain(args.base_url, args.bank, len(memories), baseline, args.drain_timeout)
    elapsed = time.time() - t0
    by = stats.get("operations_by_status") or {}
    print(f"\n  {'DRAINED' if ok else 'TIMED OUT'} after {elapsed/60:.1f} min")
    print(f"  documents={stats.get('total_documents')}/{len(memories)}  "
          f"facts={stats.get('total_nodes')}  ops={by}  "
          f"failed={stats.get('failed_operations')}")

    docs = api(args.base_url, "GET", f"{ROOT}/banks/{args.bank}/documents?limit=500")
    have = {d.get("id") for d in docs.get("items", [])}
    missing = [m["id"] for m in memories if m["id"] not in have]
    if missing:
        print(f"  NO DOCUMENT for {len(missing)}: {', '.join(missing[:12])}"
              + (" ..." if len(missing) > 12 else ""))

    if by.get("failed"):
        ops = api(args.base_url, "GET",
                  f"{ROOT}/banks/{args.bank}/operations?status=failed&limit=10")
        for op in ops.get("operations", [])[:10]:
            print(f"    FAILED {op.get('task_type')} {op.get('document_id')}: "
                  f"{(op.get('error_message') or '')[:200]}")

    out = os.path.join(args.run_dir, "run.json")
    record = {"run_id": args.run_id, "arm": args.arm}
    record.update(ran)
    record.update({
        "exclusive": args.exclusive, "image": args.image,
        "subset": os.path.basename(args.subset) if args.subset else None,
        "snapshot": {"container": snapshot.CONTAINER_FILE, "bank": snapshot.BANK_FILE},
        "bank": args.bank,
        "subset_ids": [m["id"] for m in memories],
        "submitted": len(memories),
        "submit_errors": errors, "drained": ok,
        "elapsed_min": round(elapsed / 60, 1), "stats": stats,
    })
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2)
    print(f"  wrote {out}")
    return 0 if ok and not errors else 1


if __name__ == "__main__":
    sys.exit(main())
