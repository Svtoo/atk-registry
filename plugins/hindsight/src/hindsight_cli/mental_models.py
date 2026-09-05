"""The mental-models command: list, create, update, refresh, audit, rebuild
and delete."""
import datetime
import difflib
import itertools
import json
import re
import urllib.error

from cronsim import CronSim

from . import client, shell

FIRES_CAP = 10000


def _sentence_count(query):
    return len([part for part in re.split(r"[.?!]", query) if part.strip()])


def _age(stamp, now):
    if not stamp:
        return "never"
    minutes = max(
        0, int((now - datetime.datetime.fromisoformat(stamp))
               .total_seconds() // 60))
    if minutes < 60:
        return "%dm" % minutes
    if minutes < 60 * 24:
        return "%dh" % (minutes // 60)
    return "%dd" % (minutes // (60 * 24))


def _fires_since(cron, start, now):
    count = 0
    for fire in CronSim(cron, start):
        if fire > now or count >= FIRES_CAP:
            break
        count += 1
    return count


def _call(cfg, method, path="", body=None, timeout=60):
    root = "%s/v1/default/banks/%s/mental-models" % (cfg.url, cfg.bank)
    try:
        raw = client.http(method, root + path, timeout=timeout, body=body)
    except urllib.error.URLError as error:
        shell.die("Cannot reach Hindsight at %s: %s" % (cfg.url, error),
                  "Is the service running? atk start hindsight")
    return json.loads(raw) if raw else {}


def list_models(cfg):
    # detail=metadata leaves trigger null.
    items = _call(cfg, "GET", "?detail=full").get("items", [])
    if not items:
        print("no mental models")
        return 0
    width = max(len(m["id"]) for m in items)
    for m in items:
        trigger = m.get("trigger") or {}
        print("  %-*s  %-16s  %-6s  last %s" % (
            width, m["id"], trigger.get("refresh_cron") or "(no schedule)",
            trigger.get("mode") or "full",
            (m.get("last_refreshed_at") or "never")[:16]))
    return 0


def show(cfg, model_id):
    m = _call(cfg, "GET", "/%s?detail=content" % model_id)
    print("id:      %s" % m.get("id"))
    print("name:    %s" % m.get("name"))
    print("query:   %s" % m.get("source_query"))
    print("trigger: %s" % json.dumps(m.get("trigger") or {}))
    print("content: %d chars" % len(m.get("content") or ""))
    return 0


def create(cfg, model_id, query, name, cron, max_tokens):
    if not query:
        shell.die("a mental model needs --query: the standing question it answers")
    # Observations are the consolidated layer, one entry per facet with
    # state changes already applied; raw facts are one entry per retain.
    # exclude_mental_models keeps a model off its siblings, which the
    # reflect agent otherwise ranks as its highest-quality source.
    # Delta edits the stored document instead of regenerating it; the
    # first build falls back to full because there is no baseline yet.
    trigger = {"mode": "delta", "fact_types": ["observation"],
               "exclude_mental_models": True}
    if cron:
        trigger["refresh_cron"] = cron
    body = {"id": model_id, "name": name if name is not None else model_id,
            "source_query": query, "trigger": trigger,
            "max_tokens": max_tokens}
    _call(cfg, "POST", "", body, timeout=120)
    print("  created %s" % model_id)
    if not cron:
        shell.warn("no schedule set. Add one with: --cron '0 17 * * 1,4'")
    if max_tokens > 1000:
        shell.warn("max-tokens %d: models hold their budget best at 600-800"
                   % max_tokens)
    sentences = _sentence_count(query)
    if sentences > 2:
        shell.warn("query has %d sentences: multi-facet questions produce"
                   " multi-section documents that overrun their budget"
                   % sentences)
    return 0


def set_options(cfg, model_id, query, cron, mode, max_tokens, keep_trace):
    if mode and mode not in ("delta", "full"):
        shell.die("--mode must be delta or full")
    # detail=full is the variant that reliably carries the trigger.
    current = _call(cfg, "GET", "/%s?detail=full" % model_id)
    body = {}
    if query:
        body["source_query"] = query
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    trigger_updates = {}
    if cron:
        trigger_updates["refresh_cron"] = cron
    if mode:
        trigger_updates["mode"] = mode
    if keep_trace is not None:
        trigger_updates["keep_trace"] = keep_trace
    if trigger_updates:
        body["trigger"] = {**(current.get("trigger") or {}), **trigger_updates}
    if not body:
        shell.die("nothing to set")
    _call(cfg, "PATCH", "/%s" % model_id, body)
    print("  updated %s" % model_id)
    if query:
        print("  query changed: the next refresh is a full rebuild;"
              " refresh now on approval, do not leave it for the cron")
    return 0


def _queue_refresh(cfg, model_id):
    _call(cfg, "POST", "/%s/refresh" % model_id, {}, timeout=120)
    print("  refresh queued for %s (runs in the background)" % model_id)


def refresh(cfg, model_id):
    print("  paid LLM run (cents); delta mode applies only facts newer"
          " than the last refresh")
    _queue_refresh(cfg, model_id)
    return 0


def dry_run(cfg, model_id, as_json=False):
    # The pipeline runs to completion inside the request, so this waits as
    # long as a refresh would.
    report = _call(cfg, "POST", "/%s/dry-run-refresh" % model_id, {},
                   timeout=900)
    if as_json:
        print(json.dumps(report))
        return 0
    searches = [call for call in (report.get("trace") or {}).get("tool_calls") or []
                if call.get("tool") == "search_observations"]
    facts = report.get("facts") or {}
    chars = len(report.get("candidate_content") or "")
    mode = report.get("effective_mode")
    if report.get("mode_fallback_reason"):
        mode = "%s (%s)" % (mode, report["mode_fallback_reason"])
    print("  mode %s  searches %d  facts retrieved %s used %s"
          "  candidate %d chars ~%d tokens  %ds" % (
              mode, len(searches), facts.get("retrieved"), facts.get("used"),
              chars, chars // 4, (report.get("duration_ms") or 0) // 1000))
    for warning in report.get("warnings") or []:
        print("  warning: %s" % warning)
    diff = report.get("diff") or ""
    if diff:
        print(diff, end="")
    else:
        print("  no change")
    return 0


def rebuild(cfg, model_id, yes=False):
    if not yes and not shell.confirm("Rebuild '%s' from scratch?" % model_id):
        shell.die("Aborted - nothing rebuilt.")
    _call(cfg, "POST", "/%s/clear" % model_id, {}, timeout=120)
    _queue_refresh(cfg, model_id)
    return 0


PLAYBOOK = """\
Restructuring playbook - work it in order, with the data above.

0. Existence. Does the content answer one question someone will ask before
   doing work? Content that is mostly session history or project state
   belongs in turn records, not a standing model: offer retirement.

1. The size target is the model's own budget, and it stands. Every
   strategy below moves a model toward it; none moves the target toward
   the model.
   Diagnose from the content, not the size:
   - One facet plus stray tails                    -> NARROW
   - Two or more facets, each with its own
     audience or moment of use                     -> SPLIT
   - Sound query, and the stored document is older
     than the bank (long delta accumulation)       -> REBUILD
   - RAISE BUDGET is the last resort, not a fix: it licenses the overrun.
     Offer it only after narrow, split and rebuild are each rejected for a
     stated reason, and say in the plan why this content cannot get smaller.

   REBUILD re-answers the same query over the same bank: a freshly rebuilt
   model that is still fat will come back the same size or larger. That
   case is a query or budget problem, never a rebuild problem.

   Preview before paying for a rebuild: with the model in full mode
   (set --mode full, restore delta after), dry-run <id> runs the real
   pipeline, writes nothing, and prints the diff a rebuild would land.
   It costs a refresh and predicts rather than guarantees: the real run
   samples again.

2. Narrowing must keep the model's identity. Write the new query, then
   check: same subject, tighter boundary? If the subject changed, you are
   doing a split and calling it a narrowing. A query defines a slice: a
   subject plus form constraints (rules in force, no incidents, no dates),
   never a list of contents. Name an owner, not a list of exclusions: a
   list of sibling subjects grows with every split and goes stale at the
   next one, so where two subjects meet, say in one clause which model
   owns that ground. Naming specific rules or techniques to include or
   drop pins an answer the model exists to grow past. A slice too wide is
   cut vertically into
   subjects (a split), never by carving out a content layer. The refresh
   agent reads only the memory bank. It cannot see skills, config files,
   or anything else outside memory, so a query must never reference them.

3. Splits must pay rent. Each fragment needs its own audience, its own
   subject, and enough expected use to justify its refresh cost. Two
   good models beat three thin ones. Decide the original's fate: retire
   it, or narrow it to what remains.

   Some overlap survives every split, because a rule that governs two
   subjects belongs to both. It costs a reader's tokens, not a fact:
   facts are stored once as observations and a model is a rendering over
   them. The duplicates block above says where it happened; give each
   duplicated rule one owner in that model's query and leave the rest. A
   delta refresh drops content only when a new fact contradicts it, so a
   duplicate outlives every refresh until a rebuild.

4. No edit without consent - free is not harmless. A query edit rewrites
   the model's identity, and nothing rebuilds at edit time: the NEXT
   refresh, even a cron tick days later, silently rewrites the document
   under the new question. So a query change and its refresh travel as ONE
   approved unit - propose them together, get the yes, apply both in the
   same breath. Never leave an edited query waiting for the cron.
   Once the edit is in, dry-run <id> (paid) shows the diff the refresh
   would write under the new question; present it, and the refresh gets
   its own yes.

5. Present before acting. A numbered plan: per model, the strategy, and
   for a query change the current query followed by the proposed one, set
   out so the change reads as a diff. Mark which steps are paid. One yes
   per paid step, not one yes for the batch.

6. Verify after. Re-run audit and read each rebuilt document: it must
   hold its budget AND still answer its question. Report both, including
   a failure honestly."""


# Two documents answering neighbouring questions will phrase a shared rule
# differently, so the match is on wording, not identity.
SAME_RULE = 0.6
RULES_SHOWN = 3


def _rules(content):
    """The rule-shaped sentences of a document: prose long enough to carry a
    rule, with headings and list markers stripped."""
    rules = []
    for line in (content or "").splitlines():
        line = line.strip().lstrip("-*#").strip()
        if line.startswith("|") or line.startswith("#"):
            continue
        for sentence in re.split(r"(?<=[.;])\s+", line):
            sentence = sentence.strip()
            if len(sentence) >= 40:
                rules.append(sentence)
    return rules


def _duplicates(models):
    """Rules two documents both carry, per pair of documents. Overlap is
    expected where subjects meet; this says where, so one model can own it."""
    rules = {model["id"]: _rules(model.get("content")) for model in models}
    found = []
    for first, second in itertools.combinations(models, 2):
        pairs = []
        for rule in rules[first["id"]]:
            match = max(
                ((difflib.SequenceMatcher(None, rule.lower(), other.lower())
                  .ratio(), other) for other in rules[second["id"]]),
                default=(0, ""))
            if match[0] >= SAME_RULE:
                pairs.append((rule, match[1]))
        if pairs:
            found.append((first["id"], second["id"], pairs))
    return found


def _print_duplicates(models):
    found = _duplicates(models)
    if not found:
        return
    print()
    print("duplicates")
    for first, second, pairs in found:
        print("  %s and %s both carry:" % (first, second))
        for rule, other in pairs[:RULES_SHOWN]:
            print("    %s" % _clip(rule))
            print("    %s" % _clip(other))
        if len(pairs) > RULES_SHOWN:
            print("    ... and %d more" % (len(pairs) - RULES_SHOWN))


def _clip(rule, width=120):
    return rule if len(rule) <= width else rule[:width - 3] + "..."


def _stat_line(trigger, budget, chars):
    return "  mode %s  budget %d  size %d chars ~%d tokens  ratio %.2f" % (
        trigger.get("mode") or "full", budget, chars, chars // 4,
        chars / 4 / budget)


def _review_block(model):
    trigger = model.get("trigger") or {}
    cron = trigger.get("refresh_cron")
    print(model["id"])
    print(_stat_line(trigger, model["max_tokens"],
                     len(model.get("content") or "")))
    print("  %s" % ("cron %s" % cron if cron else "no cron"))
    print("  query: %s" % model.get("source_query"))


def review(cfg, model_ids):
    items = _call(cfg, "GET", "?detail=full").get("items", [])
    if not items:
        print("no mental models")
        return 0
    known = {m["id"]: m for m in items}
    for model_id in model_ids:
        if model_id not in known:
            shell.die("no mental model '%s'" % model_id)
    targets = [known[i] for i in model_ids] if model_ids else items
    target_ids = {m["id"] for m in targets}
    for position, model in enumerate(targets):
        if position:
            print()
        _review_block(model)
    siblings = [m for m in items if m["id"] not in target_ids]
    if siblings:
        print()
        print("scope map")
        for sibling in siblings:
            print("  %s: %s" % (sibling["id"], sibling.get("source_query")))
    _print_duplicates(items)
    print()
    print(PLAYBOOK)
    return 0


def audit(cfg):
    items = _call(cfg, "GET", "?detail=full").get("items", [])
    if not items:
        print("no mental models")
        return 0
    now = shell.now_utc()
    hint_count = 0
    flagged = []
    blocks = []
    for m in items:
        lines = []
        trigger = m.get("trigger") or {}
        cron = trigger.get("refresh_cron")
        budget = m["max_tokens"]
        chars = len(m.get("content") or "")
        ratio = chars / 4 / budget
        refreshed_at = m.get("last_refreshed_at")
        lines.append(m["id"])
        lines.append(_stat_line(trigger, budget, chars))
        lines.append("  %s  last refreshed %s  last memory seen %s"
              % ("cron %s" % cron if cron else "no cron",
                 _age(refreshed_at, now),
                 _age(m.get("last_memory_seen_at"), now)))
        fires = None
        if cron and refreshed_at:
            fires = _fires_since(
                cron, datetime.datetime.fromisoformat(refreshed_at), now)
            lines.append("  %d scheduled fires since last refresh" % fires)
        hints = []
        if ratio >= 1.5:
            hints.append("over budget; run: atk run hindsight"
                         " mental-models review %s" % m["id"])
        if fires is not None and fires >= 2:
            hints.append("scheduled refreshes are not landing; a quiet scope"
                         " skips legitimately; judge against last memory seen")
        if not cron:
            hints.append("no schedule")
        for hint in hints:
            lines.append("  hint: %s" % hint)
        hint_count += len(hints)
        if hints:
            flagged.append(m["id"])
        blocks.append("\n".join(lines))
    # Both guard lines name the flagged models so a view that lost blocks
    # still carries the full flag list.
    totals = "%d models, %d hints" % (len(items), hint_count)
    if flagged:
        totals += ": " + ", ".join(flagged)
    print('auditing %s (no closing "audited" line = your view lost the tail)'
          % totals)
    print()
    print("\n\n".join(blocks))
    print()
    print('audited %s (no opening "auditing" line = your view lost the head)'
          % totals)
    return 1 if hint_count else 0


def delete(cfg, model_id, yes=False):
    if not yes and not shell.confirm("Delete mental model '%s'?" % model_id):
        shell.die("Aborted - nothing deleted.")
    _call(cfg, "DELETE", "/%s" % model_id)
    print("  deleted %s" % model_id)
    return 0
