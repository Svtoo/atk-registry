#!/usr/bin/env python3
"""Migrate OpenMemory memories into Hindsight.

Stages are separate subcommands so each can be inspected before the next runs:
export, tags, plan, apply, verify. The plan stage is a hard gate; apply refuses
to run until every project group has a confirmed target.
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import Counter

# Rows whose content is a captured agent tool call rather than a memory.
JUNK = ("<parameter name=", "</content>", "</invoke>")

POLL_SECONDS = 5
BANK_NAME = re.compile(r"[A-Za-z0-9._-]+")
# uuid5 needs a namespace, and the value has to be a fixed literal: the same
# bank and source row must derive the same operation id on every machine and
# every run, or Hindsight sees a resubmission as new work. Any constant serves;
# this one is arbitrary and belongs to this script.
OP_NAMESPACE = uuid.UUID("6f2a1c4e-8d3b-4f7a-9e15-2c8b0a6d4319")
TERMINAL = ("completed", "failed", "cancelled", "not_found")

EXPORT_JS = """
const sqlite3 = require("/app/node_modules/sqlite3");
const db = new sqlite3.Database(process.argv[1], sqlite3.OPEN_READONLY);
db.get("SELECT COUNT(*) AS n FROM memories", (err, row) => {
  if (err) { console.error(err.message); process.exitCode = 1; return; }
  process.stdout.write(JSON.stringify({__count: row.n}) + "\\n");
  db.each("SELECT id, content, tags, primary_sector, created_at, updated_at FROM memories",
    (err, row) => {
      if (err) { console.error(err.message); process.exitCode = 1; return; }
      process.stdout.write(JSON.stringify(row) + "\\n");
    },
    (err) => { if (err) { console.error(err.message); process.exitCode = 1; } db.close(); });
});
"""


def die(msg, hint=None):
    print(f"migrate_openmemory: {msg}", file=sys.stderr)
    if hint:
        print(f"  {hint}", file=sys.stderr)
    raise SystemExit(1)


def iso(epoch_ms, source_id):
    dt = datetime.datetime.fromtimestamp(epoch_ms / 1000.0, datetime.timezone.utc)
    if dt.year < 2015:
        die(f"memory {source_id} has created_at {epoch_ms}, which is not milliseconds "
            f"since the epoch (it reads as {dt.year})",
            "Migrating it would collapse the corpus timeline.")
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def save_json(path, obj, indent=1):
    tmp = f"{path}.tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, indent=indent)
    os.replace(tmp, path)


def read_json(path, what):
    try:
        with open(path) as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as e:
        die(f"{what} at {path} is not valid JSON: {e}")


def read_rows(path):
    rows = []
    with open(path) as fh:
        for n, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                die(f"{path} line {n} is not valid JSON: {e}")
            for key in ("id", "content", "tags", "created_at"):
                if key not in row:
                    die(f"{path} line {n} has no {key!r}; regenerate it with the export subcommand")
            rows.append(row)
    if not rows:
        die(f"{path} has no rows; there is nothing to migrate")
    return rows


def api(base, method, path, body=None, timeout=180):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        die(f"{method} {path} returned {e.code}: {e.read().decode()[:300]}")
    except urllib.error.URLError as e:
        die(f"{method} {path} could not reach {base}: {e.reason}",
            "Check HINDSIGHT_URL, or pass --url.")
    except (TimeoutError, OSError, json.JSONDecodeError) as e:
        die(f"{method} {path} failed: {type(e).__name__}: {e}")


def check_bank_name(bank):
    if not BANK_NAME.fullmatch(bank):
        die(f"bank name {bank!r} may contain only letters, digits, dot, dash and underscore")


def require_bank(base, bank, create):
    check_bank_name(bank)
    existing = [b["bank_id"] for b in api(base, "GET", "/v1/default/banks")["banks"]]
    if bank in existing:
        return
    if not create:
        die(f"bank {bank!r} does not exist",
            "Hindsight creates banks on first write, so a typo here migrates into a bank "
            "nothing will ever read from. Pass --create-bank if you meant to make a new "
            f"one. Existing banks: {', '.join(sorted(existing))}")
    api(base, "PUT", f"/v1/default/banks/{bank}", {})
    print(f"created bank {bank!r}")


def parse_tags(raw, source_id):
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        die(f"memory {source_id} has a tags column that is not JSON: {raw!r}")
    if not isinstance(parsed, list) or not all(isinstance(t, str) for t in parsed):
        die(f"memory {source_id} has a tags column that is not a list of strings: {raw!r}")
    return parsed


def cmd_export(args):
    try:
        proc = subprocess.run(
            ["docker", "exec", args.container, "node", "-e", EXPORT_JS, args.db],
            capture_output=True, text=True,
        )
    except FileNotFoundError:
        die("docker is not on PATH", "Start Docker, then rerun.")
    if proc.returncode != 0:
        die(f"reading the OpenMemory database failed: {proc.stderr.strip()}",
            f"Is the container {args.container!r} running? Check: docker ps")

    lines = [l for l in proc.stdout.splitlines() if l.strip()]
    if not lines:
        die("the OpenMemory database produced no output")
    header = json.loads(lines[0])
    if "__count" not in header:
        die("unexpected output from the OpenMemory database; expected a row count first")
    expected = header["__count"]

    kept, dropped = [], []
    for line in lines[1:]:
        row = json.loads(line)
        content = row.get("content") or ""
        if any(marker in content for marker in JUNK):
            dropped.append(row)
            continue
        row["tags"] = parse_tags(row.get("tags"), row["id"])
        kept.append(row)

    # node's stdout is asynchronous over a pipe, so a short read is possible and
    # would otherwise look like a smaller corpus rather than a failure.
    if len(kept) + len(dropped) != expected:
        die(f"read {len(kept) + len(dropped)} of {expected} memories from the database",
            "The export was truncated. Rerun; if it repeats, report it rather than migrating.")

    with open(args.out, "w") as fh:
        for row in kept:
            fh.write(json.dumps(row) + "\n")
    if not kept:
        die(f"all {expected} memories look like captured tool calls; nothing to migrate")

    print(f"exported {len(kept)} of {expected} memories to {args.out}")
    if dropped:
        dropped_path = args.out + ".dropped"
        with open(dropped_path, "w") as fh:
            for row in dropped:
                fh.write(json.dumps(row) + "\n")
        print(f"set aside {len(dropped)} captured tool calls in {dropped_path}")


def cmd_tags(args):
    counts = Counter()
    untagged = 0
    for row in read_rows(args.jsonl):
        if not row["tags"]:
            untagged += 1
        counts.update(row["tags"])
    for tag, n in counts.most_common():
        print(f"{n:6d}  {tag}")
    print(f"\n{len(counts)} distinct tags, {untagged} memories with no tags at all")


CONSEQUENCE = """
STOP. Rewriting these tags after the migration means migrating again.

Hindsight merges duplicate facts only when their tag sets are identical. Split
one project across two tags and its duplicates never combine, so the store keeps
several drifting versions of the same fact instead of one settled version. A
recall scoped to a project also misses anything filed under a different tag,
though an unscoped recall still finds everything.

Fill in "target" for every group below with the directory name you work in,
lowercase and without a path. Use "" to migrate those memories with no tag at
all. Do not guess. Ask.
"""


def cluster(tags):
    """Group project tags by their leading token, as a suggestion only."""
    groups = {}
    for tag in tags:
        key = tag[len("project-"):].split("-")[0].lower()
        groups.setdefault(key, []).append(tag)
    return groups


def cmd_plan(args):
    if os.path.exists(args.out) and not args.force:
        die(f"{args.out} already exists",
            "Overwriting discards every target filled in so far. Pass --force to do it anyway.")

    counts, untagged = Counter(), 0
    for row in read_rows(args.jsonl):
        proj = [t for t in row["tags"] if t.lower().startswith("project-")]
        if not proj:
            untagged += 1
        counts.update(proj)
    if not counts:
        die(f"{args.jsonl} has no project-* tags",
            "Every memory migrates untagged; run apply with a plan containing no groups.")

    grouped = cluster(counts)
    plan = {
        "rows_without_project_tag": untagged,
        "all_tags": sorted(counts),
        # Filled in only if apply reports memories belonging to several projects.
        "precedence": [],
        "groups": [
            {
                "tags": sorted(members, key=lambda t: -counts[t]),
                "memories": sum(counts[t] for t in members),
                "target": None,
            }
            for _, members in sorted(grouped.items(),
                                     key=lambda g: -sum(counts[t] for t in g[1]))
        ],
    }
    save_json(args.out, plan, indent=2)

    print(CONSEQUENCE)
    for g in plan["groups"]:
        print(f"  {g['memories']:5d} memories  {', '.join(g['tags'])}")
    print(f"\n  {untagged} memories carry no project tag and will migrate untagged.")
    print(f"\nWrote {args.out}. Every group needs a target before migration can run.")


def load_plan(path):
    plan = read_json(path, "plan")
    if plan is None:
        die(f"no plan at {path}", "Create one with the plan subcommand.")
    for key in ("groups", "all_tags"):
        if key not in plan:
            die(f"{path} has no {key!r} key; regenerate it with the plan subcommand")

    blank = [g["tags"] for g in plan["groups"] if g.get("target") is None]
    if blank:
        die(f"{len(blank)} group(s) still have target=null, first is {blank[0]}",
            "Every project must be disambiguated with the user before migrating.")

    for g in plan["groups"]:
        target = g["target"]
        if not isinstance(target, str):
            die(f"target for {g['tags']} must be a string, got {target!r}",
                'Use "" to migrate that group untagged.')
        if target != target.strip() or target != target.lower() or "/" in target:
            die(f"target {target!r} must be a bare lowercase directory name",
                "Not a path and not capitalised. It has to match the tag the agent "
                "writes, or these memories never merge with the ones it writes later.")

    # Groups are a heuristic suggestion the user is expected to split or merge.
    # Editing them by hand must not silently drop a tag.
    placed = Counter(t for g in plan["groups"] for t in g["tags"])
    expected = set(plan["all_tags"])
    missing = expected - set(placed)
    extra = set(placed) - expected
    dupes = [t for t, n in placed.items() if n > 1]
    if missing or extra or dupes:
        die(f"plan does not cover the tags exactly once: missing={sorted(missing)} "
            f"unknown={sorted(extra)} duplicated={sorted(dupes)}")

    # Optional: only a corpus where some memory belongs to two projects needs it.
    precedence = plan.get("precedence") or []
    if not isinstance(precedence, list) or not all(isinstance(p, str) for p in precedence):
        die('"precedence" must be a list of target names, most important first')
    targets = {g["target"] for g in plan["groups"]} - {""}
    unknown = [p for p in precedence if p not in targets]
    if unknown:
        die(f"precedence names {unknown}, which no group migrates into",
            "A name that matches no target silently ranks nothing. Targets in this "
            f"plan: {', '.join(sorted(targets))}")
    if len(set(precedence)) != len(precedence):
        die(f"precedence repeats a name: {precedence}")
    plan["precedence"] = precedence
    return plan


def tag_map(plan):
    """Old OpenMemory tag -> its project: tag, or None when it migrates untagged."""
    return {t: (f"project:{g['target']}" if g["target"] else None)
            for g in plan["groups"] for t in g["tags"]}


def targets_for(row, mapping):
    """Every project tag this memory's old tags resolve to, before precedence."""
    return sorted({mapping[t] for t in row["tags"] if mapping.get(t)})


def resolve_targets(row, mapping, precedence):
    """The one tag a memory should carry, or every competitor when the plan is silent.

    Hindsight merges facts only within a matching tag set, so a memory carrying
    two project tags lands in a scope of its own and merges with neither project.
    One tag per memory is the invariant; precedence is how the user breaks the
    tie once for the whole corpus instead of per memory.
    """
    targets = targets_for(row, mapping)
    if len(targets) < 2:
        return targets
    ranked = [f"project:{name}" for name in precedence]
    # Every competitor has to be ranked. A precedence naming only some of them
    # says nothing about how the unnamed ones compare, so the tie still stands.
    if all(t in ranked for t in targets):
        return [min(targets, key=ranked.index)]
    return targets


def conflict_groups(rows, mapping, precedence):
    """Memories precedence cannot resolve, grouped by the targets competing for them."""
    groups = {}
    for row in rows:
        targets = resolve_targets(row, mapping, precedence)
        if len(targets) < 2:
            continue
        group = groups.setdefault(tuple(targets),
                                  {"count": 0, "tags": [], "sample": row["id"]})
        group["count"] += 1
        for tag in sorted(row["tags"]):
            if mapping.get(tag) and tag not in group["tags"]:
                group["tags"].append(tag)
    return groups


def report_multi_project(conflicts):
    """Say which memories span projects and what they were tagged with.

    A memory that belongs to two projects carries both tags, so it comes back
    from either one. That costs merging: consolidation combines duplicates only
    within an identical tag set, so these facts do not merge with the
    single-tagged ones. A plan that would rather have one tag says so with
    "precedence". Neither answer is worth stopping a migration over, so this
    reports and continues.
    """
    total = sum(g["count"] for g in conflicts.values())
    ranked = sorted(conflicts.items(), key=lambda kv: -kv[1]["count"])
    print(f"{memories(total)} {agrees(total, 'belongs', 'belong')} to more than one "
          f"project and {agrees(total, 'keeps', 'keep')} every tag, in "
          f"{len(ranked)} {agrees(len(ranked), 'combination', 'combinations')}:")
    suggestion = []
    for targets, group in ranked:
        names = [t[len("project:"):] for t in targets]
        noun = "memory" if group["count"] == 1 else "memories"
        print(f"  {group['count']:5d} {noun:8s} {' + '.join(names)}"
              f"   (from {', '.join(group['tags'])})")
        suggestion += [n for n in names if n not in suggestion]
    print('  To give these one tag each instead, add "precedence" to the plan, '
          "most important project first:")
    print(f'      "precedence": {json.dumps(suggestion)}')


def all_untagged(plan):
    """True when no group carries a project tag, which is what an unanswered plan
    looks like: filling every target with "" satisfies the null check without
    anyone having decided anything."""
    return bool(plan["groups"]) and all(not g["target"] for g in plan["groups"])


def rows_in_scope(rows, limit):
    return rows[:limit] if limit else rows


def memories(n):
    return f"{n} memory" if n == 1 else f"{n} memories"


def agrees(n, singular, plural):
    return singular if n == 1 else plural


def checkpoint_path(args):
    # Keyed on the bank as well as the export: migrating the same memories into a
    # second bank is a separate migration, not a continuation of the first.
    return args.checkpoint or f"{args.jsonl}.{args.bank}.checkpoint"


def cmd_apply(args):
    if args.limit < 0:
        die("--limit must be zero or greater")
    base = args.url.rstrip("/")
    require_bank(base, args.bank, args.create_bank)

    plan = load_plan(args.plan)
    if all_untagged(plan) and not args.all_untagged:
        die("every group in this plan migrates untagged",
            "That is the shape of a plan nobody answered. It throws away the "
            "scoping the corpus already had, and getting it back means migrating "
            "again. Go through the groups with the user, including on a sample "
            "run. If their memories genuinely cover no projects at all, say so "
            "with --all-untagged.")
    mapping = tag_map(plan)
    precedence = plan["precedence"]
    ckpt_path = checkpoint_path(args)
    ckpt = read_json(ckpt_path, "checkpoint") or {}

    rows = rows_in_scope(read_rows(args.jsonl), args.limit)

    # Reported before any network call, so the tagging is visible up front
    # rather than discovered in the bank afterwards.
    conflicts = conflict_groups(rows, mapping, precedence)
    if conflicts:
        report_multi_project(conflicts)
    settled = sum(1 for r in rows
                  if len(targets_for(r, mapping)) > 1 and not
                  conflict_groups([r], mapping, precedence))
    if settled:
        print(f"{memories(settled)} {agrees(settled, 'belongs', 'belong')} to more than "
              f"one project; precedence {' > '.join(precedence)} decided which single "
              f"tag each one carries")

    todo = [r for r in rows if ckpt.get(r["id"], {}).get("status") != "completed"]
    print(f"{len(rows)} memories, {len(rows) - len(todo)} already migrated, {len(todo)} to send")
    if not todo:
        return

    for start in range(0, len(todo), args.batch):
        batch = todo[start : start + args.batch]
        try:
            for row in batch:
                body = {
                    "items": [{
                        "content": row["content"],
                        "timestamp": iso(row["created_at"], row["id"]),
                        "tags": resolve_targets(row, mapping, precedence),
                        # Reusing the OpenMemory row id means a resubmission updates
                        # that document instead of creating a second one.
                        "document_id": row["id"],
                    }],
                    "async": True,
                    "operation_id": str(uuid.uuid5(OP_NAMESPACE, f"{args.bank}/{row['id']}")),
                }
                resp = api(base, "POST", f"/v1/default/banks/{args.bank}/memories", body)
                ckpt[row["id"]] = {"operation_id": resp["operation_id"], "status": "submitted"}
                save_json(ckpt_path, ckpt)

            pending = {r["id"] for r in batch}
            deadline = time.time() + args.timeout
            while pending and time.time() < deadline:
                time.sleep(POLL_SECONDS)
                for src_id in list(pending):
                    state = api(base, "GET",
                                f"/v1/default/banks/{args.bank}/operations/{ckpt[src_id]['operation_id']}")
                    status = state.get("status")
                    if status in TERMINAL:
                        ckpt[src_id]["status"] = status
                        if status != "completed":
                            ckpt[src_id]["error"] = str(state.get("error_message") or status)[:300]
                        pending.discard(src_id)
            for src_id in pending:
                ckpt[src_id]["status"] = "timeout"
                ckpt[src_id]["error"] = f"still running after {args.timeout}s"
        except KeyboardInterrupt:
            save_json(ckpt_path, ckpt)
            die(f"interrupted; progress saved to {ckpt_path}",
                "Rerun the same command to continue where this left off.")
        finally:
            save_json(ckpt_path, ckpt)

        n = start // args.batch + 1
        done = sum(1 for r in rows if ckpt.get(r["id"], {}).get("status") == "completed")
        print(f"  after batch {n}: {done}/{len(rows)} migrated")

    print(f"checkpoint at {ckpt_path}")


def cmd_verify(args):
    if args.limit < 0:
        die("--limit must be zero or greater")
    base = args.url.rstrip("/")
    check_bank_name(args.bank)
    full = read_json(checkpoint_path(args), "checkpoint")
    if not full:
        die("no checkpoint found", "Run apply first.")
    all_rows = read_rows(args.jsonl)
    rows = rows_in_scope(all_rows, args.limit)
    # Judge only what this run was asked to migrate, so a sampled migration can
    # report a clean result instead of failing on the memories it never sent.
    scope = {r["id"] for r in rows}
    ckpt = {k: v for k, v in full.items() if k in scope}
    never = [r["id"] for r in rows if r["id"] not in ckpt]
    by_status = Counter(v["status"] for v in ckpt.values())

    facts, offset = [], 0
    while True:
        page = api(base, "GET",
                   f"/v1/default/banks/{args.bank}/memories/list?limit=100&offset={offset}")
        items = page["items"]
        if not items:
            break
        facts.extend(items)
        offset += len(items)

    # Consolidated observations carry no document_id; they derive from facts that
    # do, so attribution is only meaningful over the extracted facts.
    attributed = [f for f in facts if f.get("document_id")]
    produced = Counter(f["document_id"] for f in attributed)
    completed = [k for k, v in ckpt.items() if v["status"] == "completed"]
    silent = [k for k in completed if produced.get(k, 0) == 0]

    if args.limit:
        print(f"checking the first {len(rows)} of {len(all_rows)} memories "
              f"in {args.jsonl}, as --limit says")
    print(f"memories in scope        {len(rows)}")
    print(f"submitted                {len(ckpt)}")
    for status, n in by_status.most_common():
        print(f"  {status:14s} {n}")
    print(f"\nwhole bank {args.bank!r}, including anything already there:")
    print(f"  facts               {len(facts)}  ({len(attributed)} extracted, "
          f"{len(facts) - len(attributed)} observations)")
    print(f"  dated facts         {sum(1 for f in facts if f.get('occurred_start'))}")
    print(f"  tags                {sorted({t for f in facts for t in (f.get('tags') or [])})}")

    problems = bool(never) or bool(silent) or any(
        v["status"] != "completed" for v in ckpt.values())
    print()
    if never:
        print(f"INCOMPLETE {len(never)} of the {len(rows)} memories in scope were never "
              f"submitted; rerun apply, or pass verify the same --limit apply had")
    if silent:
        print(f"WARNING {len(silent)} memories completed but produced no facts "
              f"(showing up to 10 of {len(silent)}):")
        for k in silent[:10]:
            print(f"  {k}")
    for k, v in ckpt.items():
        if v.get("error"):
            print(f"FAILED {k}: {v['error']}")
    if not problems:
        print(f"OK every one of the {len(rows)} memories migrated and produced facts")
    raise SystemExit(1 if problems else 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    export = sub.add_parser("export", help="dump OpenMemory memories to JSONL")
    export.add_argument("out")
    export.add_argument("--container", default="openmemory")
    export.add_argument("--db", default="/data/openmemory.sqlite")
    export.set_defaults(func=cmd_export)

    tags = sub.add_parser("tags", help="tag vocabulary with counts")
    tags.add_argument("jsonl")
    tags.set_defaults(func=cmd_tags)

    plan = sub.add_parser("plan", help="emit the project mapping the user must fill in")
    plan.add_argument("jsonl")
    plan.add_argument("out")
    plan.add_argument("--force", action="store_true",
                      help="overwrite an existing plan, discarding its targets")
    plan.set_defaults(func=cmd_plan)

    apply_ = sub.add_parser("apply", help="migrate memories using the confirmed plan")
    apply_.add_argument("jsonl")
    apply_.add_argument("plan")
    apply_.add_argument("--bank", default=os.environ.get("HINDSIGHT_BANK", "default"),
                        help="memory bank to migrate into (default: $HINDSIGHT_BANK)")
    apply_.add_argument("--url", default=os.environ.get("HINDSIGHT_URL", "http://localhost:8888"))
    apply_.add_argument("--batch", type=int, default=20)
    apply_.add_argument("--limit", type=int, default=0, help="migrate only the first N memories")
    apply_.add_argument("--timeout", type=int, default=1800, help="seconds to wait per batch")
    apply_.add_argument("--all-untagged", action="store_true",
                        help="the user confirmed their corpus covers no projects, so "
                             "every group migrating untagged is the real answer")
    apply_.add_argument("--create-bank", action="store_true",
                        help="create the bank if it does not exist yet")
    apply_.add_argument("--checkpoint")
    apply_.set_defaults(func=cmd_apply)

    verify = sub.add_parser("verify", help="reconcile what was migrated against what landed")
    verify.add_argument("jsonl")
    verify.add_argument("--bank", default=os.environ.get("HINDSIGHT_BANK", "default"),
                        help="memory bank to check (default: $HINDSIGHT_BANK)")
    verify.add_argument("--url", default=os.environ.get("HINDSIGHT_URL", "http://localhost:8888"))
    verify.add_argument("--limit", type=int, default=0,
                        help="check only the first N memories; pass the same value "
                             "apply was given, or its exit code counts the memories "
                             "that run was never asked to migrate as missing")
    verify.add_argument("--checkpoint")
    verify.set_defaults(func=cmd_verify)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
