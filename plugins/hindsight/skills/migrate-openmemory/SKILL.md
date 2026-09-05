---
name: migrate-openmemory
description: Migrate an existing OpenMemory corpus into Hindsight, preserving each memory's original timestamp and mapping OpenMemory's free-form tags onto one project tag per memory. Use whenever someone with existing OpenMemory data mentions moving, importing, porting, or migrating it to Hindsight, or asks what to do with their old memories after installing Hindsight, even if they do not say "migrate". Not for a fresh Hindsight install with no prior OpenMemory data.
---

# Migrating OpenMemory into Hindsight

Every step is a subcommand of `scripts/migrate_openmemory.py`, already written.
**Do not write code for this task.** Your only edits are the `target` fields in
`plan.json`, filled with values the user gives you.

Run every command from the directory holding this file, or prefix `scripts/`
with its absolute path.

**Read this before anything else.** Once a memory is ingested it cannot be
pulled back out: extraction and consolidation fold it into observations shared
with everything else in the bank. A bad run into a bank that already holds
memories is hard or impossible to undo. Say this to the user in plain words
before step 4 and get a yes. Prefer a bank that holds nothing yet: a fresh
install's configured bank, or a new one made for this migration (`--bank <name>
--create-bank`, then `atk setup hindsight` to point the plugin at it once step 5
checks out). Never delete anything on your own initiative; ask.

## Why this needs a human

Two different costs, and they are worth keeping straight.

A **bank** is a hard boundary. The agent's tools are scoped to one bank and
cannot name another, so memories in the wrong bank are unreachable to it.

A **tag** is a filter that is off by default. A recall that passes no tags
searches everything, so a wrongly tagged memory is still findable. Two things do
break. A recall scoped to a project excludes other tags outright, with no partial
credit. And consolidation merges duplicates only across identical tag sets, so an
inconsistently tagged corpus accumulates drifting near-copies of one fact instead
of settling on a single version.

Neither cost announces itself, which is why step 3 asks rather than guesses.

## Before you start

- **The OpenMemory container must still be running**: `docker ps | grep openmemory`.
  Export reads its database with `docker exec`. Do not let the user uninstall or
  remove OpenMemory until step 5 confirms the migration landed.
- Hindsight must be healthy: `curl -fsS "$HINDSIGHT_URL/health"`.
- Work in a scratch directory, not inside the plugin. `om.jsonl`, `plan.json`
  and the checkpoint all land in the working directory.
- Memories migrate into the bank the plugin is configured for. A plain shell
  does not carry it, so read it rather than assume it: `atk mcp hindsight --json`
  prints `HINDSIGHT_URL` and `HINDSIGHT_BANK`. Pass both to every command as
  `--url` and `--bank`. Without them the scripts fall back to
  `http://localhost:8888` and the bank named `default`, which is a silent wrong
  answer when the user's bank is named anything else. Add `--create-bank` if the
  bank is new.

## 1. Export

```
python3 scripts/migrate_openmemory.py export om.jsonl
```

Reads OpenMemory's SQLite database out of its container and writes one JSON
object per line, checking the row count so a short read fails instead of looking
like a smaller corpus. Rows whose content is a captured agent tool call go to
`om.jsonl.dropped` rather than being discarded, so the user can inspect them.

Defaults to container `openmemory` and database `/data/openmemory.sqlite`. Pass
`--container` / `--db` if theirs differ; `docker ps` shows the container name.

## 2. Discover the tag vocabulary

```
python3 scripts/migrate_openmemory.py tags om.jsonl
python3 scripts/migrate_openmemory.py plan om.jsonl plan.json
```

`tags` prints every distinct tag with counts. OpenMemory tags were free-form, so
expect noise. `plan` ignores that and groups only the `project-*` tags, which is
the subset that decides scoping, writing each group with `"target": null`.

Report to the user: total memories, how many carry a project tag, how many do
not, and the group list. Numbers first, then the question.

## 3. Disambiguate with the user, and stop here

Ask which **directory on their machine** each group belongs to. Present it as a
numbered list they can answer in one message.

Tell them what a wrong answer costs, using the reasoning above. They cannot weigh
the question without it.

- Never guess a directory, and never infer one from a project's name. A tag
  reading `project-acme` does not tell you the repo is called that.
- The grouping is a leading-token heuristic and is regularly wrong. Two unrelated
  projects sharing a first word, like `project-acme-web` and
  `project-acme-billing`, land in one group. Offer to split any group; they may
  also merge groups.
- `""` as a target migrates that group untagged. That is right for anything that
  is not a codebase, and for facts true regardless of what the user is working on.
  It is an answer for one group, never a way to answer all of them at once: a
  corpus migrated untagged has lost the scoping it arrived with, and getting it
  back means migrating again. `apply` refuses a plan where every group is `""`.
  This holds for the sample run too — a sample is only worth reading if it landed
  the way the real migration will.
- Memories with no project tag migrate untagged. Say how many.

Then write their answers into the `target` fields. A group object has exactly two
keys the loader reads: `"tags"`, the list of old OpenMemory tags, and `"target"`,
the directory name or `""`. To split a group, move tags into a new group object.
Never delete a tag: the loader checks that every tag is still covered exactly
once and fails if one goes missing.

A memory can carry tags from two projects at once, which no target mapping can
settle. `apply` reports those before it sends anything; step 4 covers what to
ask.

## 4. Migrate a sample and read it

```
python3 scripts/migrate_openmemory.py apply om.jsonl plan.json --limit 20
python3 scripts/migrate_openmemory.py verify om.jsonl --limit 20
```

`verify` reconciles the export against what landed. It exits non-zero and says
`INCOMPLETE` if any memory was never submitted, so trust its exit code rather
than reading past a wall of counts. Numbers under `whole bank` cover everything
in the bank, including memories that were already there before the migration.

**Give `verify` the same `--limit` you gave `apply`.** Without it, `verify`
judges the whole export, counts every memory this run was never asked to send as
missing, and always exits non-zero — which makes its exit code useless exactly
when you are sampling.

A memory tagged for two projects at once keeps both tags and comes back from
either project. `apply` says how many and in which combinations. That costs
merging: consolidation combines duplicates only within an identical tag set, so
those facts never merge with the single-tagged ones. If the user would rather
each memory carried one tag, ask them to rank the projects, most important first,
and put that ranking in the plan as `"precedence"`; the earliest name wins.
Either way the migration runs.

Then show the user two or three extracted facts beside their source text. Fact
counts say nothing about whether extraction was faithful.

## 5. Migrate the rest

```
python3 scripts/migrate_openmemory.py apply om.jsonl plan.json
python3 scripts/migrate_openmemory.py verify om.jsonl
```

Batched, with a checkpoint written after every memory. Safe to interrupt:
rerunning the same command skips what already completed. The checkpoint is named
after both the export and the bank, so migrating the same memories into a second
bank starts fresh rather than reporting them all done. Each memory carries its original
creation time, so the corpus keeps its real timeline instead of collapsing to the
migration date, and its source id, so a repeat submission updates rather than
duplicates.

`--batch` defaults to 20. Hindsight caps concurrent extraction calls, so a larger
batch does not finish sooner; it only makes a batch more likely to hit
`--timeout`, which is 1800 seconds per batch.

Finish by reporting the final counts and telling the user that OpenMemory can now
be removed, and that `om.jsonl`, `plan.json` and the checkpoint are safe to delete
once they are satisfied. Do not remove any of it yourself.

## When a step fails

- **`apply` reports memories belonging to several projects.** Not a failure. They
  migrate with every tag they belong to. Add `"precedence"` to the plan only if
  the user wants one tag per memory instead.
- **`verify` says INCOMPLETE, or shows `failed` or `timeout` rows.** Rerun the
  same `apply` command. Completed rows are skipped and only the rest are resent.
  `timeout` means the batch outran `--timeout`, not that extraction is broken.
  Resubmitting the same memory updates it rather than duplicating it, so a rerun
  is safe even if the checkpoint was lost.
- **`verify` warns that completed memories produced no facts.** The model found
  nothing durable in them. A handful is normal. Many means the extraction model
  is wrong for the job, so stop and raise it with the user rather than migrating
  the rest.
- **The step 4 sample reads wrong.** Stop and show the user what landed beside
  its source text. Do not delete anything on your own. If the bank held nothing
  before this migration, `atk run hindsight banks delete <bank>` and a new
  extraction model is a clean restart, and still the user's call. If it already
  held memories, the sample is now folded into them and cannot be pulled back
  out; say so, and let the user decide whether to change the model and continue,
  or stop here.
