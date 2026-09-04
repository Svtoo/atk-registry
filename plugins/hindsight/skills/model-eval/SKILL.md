---
name: model-eval
description: Evaluate a candidate extraction model for Hindsight on a frozen corpus against the production stack, and compare it with every recorded run. Use whenever someone wants to evaluate a model for Hindsight, run a bake-off, ask which extraction model to use, test a candidate model, or check whether an image upgrade changed what extraction keeps, even if they do not say "eval". Not for switching production's model, which is `atk setup hindsight`.
---

# Evaluating an extraction model

Every step is a subcommand of `scripts/model-eval.sh`, already written.
**Do not write code for this task.** Your only edit is the entry that
registers a new arm (step 1).

Run every command from the directory holding this file, or prefix `scripts/`
with its absolute path. The scripts and the corpus live under this directory;
results never do. The skill finds the hindsight plugin through ATK's home and
reads the provider and key the plugin already holds, so there is nothing to
configure. Point it elsewhere with `ATK_HOME`, or `HINDSIGHT_PLUGIN_DIR` for
the plugin itself.

## What a run measures

An arm is one model on one provider, behind a host pin when the provider is
OpenRouter, run through production's own stack: same image, same embeddings,
same retain instructions, same bank settings, all copied from a snapshot of
the running production container taken as the run starts, and checked against
that snapshot before anything is spent. The model is the only variable.

The write side (`ingest`) loads a fixed subset of a synthetic corpus and scores
what survived. **Survival** is the share of hard tokens (paths, flags,
signatures, numbers) that appear verbatim in the facts extracted from that same
memory. **Silent losses** are memories that produced no facts while the retain
reported success. **Expansion** is fact characters per source character, which
catches a model that copies instead of extracting.

The read side (`read`) asks the same model to get those facts back. **recall@k**
runs a frozen query set where each query is the surrounding prose with the
target literal removed. **Reflect literal hit rate** is whether the literal
survives into a synthesised answer. **Mental models** count literals carried
per 1k characters of a standing synthesis, since that content is context an
agent pays for on every load.

## Before you start

- Production Hindsight must be running and healthy: `atk status hindsight`.
  `ingest` snapshots its settings and refuses to run without it. Never stop
  or reconfigure it for a run yourself. The one exception is an exclusive
  local arm (step 4), which the command stops only after the user types yes.
- Host Ollama must serve the embeddings model production uses. Embeddings are
  held constant across arms; a substitute changes what is measured.
- The key is always the plugin's own `HINDSIGHT_LLM_API_KEY`, which ATK hands
  to every command. There is no key file, and nothing in this skill reads one.
  That key belongs to production's provider, `HINDSIGHT_LLM_PROVIDER`. An
  arm on a different provider needs a key for that provider, and `ingest`,
  `read` and `pin` stop and say so. When they do, ask the user to swap the
  plugin key: set `HINDSIGHT_LLM_API_KEY` in the plugin's `.env` (what
  `atk setup hindsight` writes) to a key for the arm's provider, rerun with
  `--key-is-for <provider>` naming the arm's provider, and swap it back when
  the run is over. The swap is safe for production: the running container
  keeps the key it started with, and only the next `atk restart hindsight`
  would read the swapped value, so the user must swap back before restarting.
  A shell export cannot stand in, because `.env` wins over the shell
  environment. Never invent, look up, reuse or guess a key, and never write
  one to a file yourself. An Ollama arm goes through the same gate; Ollama
  ignores the key, so `not-needed` is a fine value.
- **A run spends real money** on a hosted provider. On the recorded runs,
  ingest plus read of the 52-memory subset cost between a quarter and three
  dollars per arm, set by the model's price. Say so before starting one, and
  run `cost` afterwards for the measured figure.
- The eval container is exclusive: `ingest` and `read` recreate it, so nothing
  else may be using it. Its volumes are kept, and earlier runs' banks survive.

`preflight` checks all of the above and writes nothing.

## Run order

### 0. Preflight

```
scripts/model-eval.sh preflight
```

### 1. Register the arm, if it is new

An arm is one entry in `scripts/arms.yaml`: `id`, `key`, `provider`, `model`,
`base_url`, `strict_schema`, `max_concurrent` and a `note` that says why the
arm exists. Known arms: `python3 scripts/armsfile.py --list`. Keys are
lowercase letters, digits and underscores, and the key appears in the run id.

`provider` is any provider the plugin supports: `ollama`, `openrouter`,
`groq`, `openai`, `anthropic`, or `openai` with `base_url` set for any other
OpenAI-compatible endpoint. Leave `base_url` empty for the provider's default;
an `ollama` arm with it empty reaches the host's Ollama from inside the
container. `strict_schema: false` is for a provider that cannot enforce a
schema: such an arm measures JSON-mode extraction, its `note` must say so, and
its runs are flagged not schema-comparable. `max_concurrent` is the in-flight
request count the eval server allows for this arm; a local runner with one
slot wants 1.

### 2. Build the pin (openrouter arms only)

```
scripts/model-eval.sh pin <arm>
```

Lists every OpenRouter endpoint for the arm's model with its verdict under two
filters: quantization fp8 or better, and `structured_outputs` supported. Hosts
in production's own pin, read live from the container, are marked and put
first in the proposal: the eval measures the stack that will be deployed, so
a host production never uses measures something else. The rest of the
proposal is the best remaining candidates by uptime, four hosts in all.

**Show the table to the user and get a yes on the pin before spending.** A pin
is built per run, never reused: hosts come and go, prices move, and
production's pin moves. Each arm's `note` in `scripts/arms.yaml` records the
pin its earlier runs used so a result can be traced to its hosts; it is a
record, not an input. Two runs on different hosts are two measurements of
different serving stacks, and their numbers are compared with that in mind.

A pin is an OpenRouter concept. `ingest` requires `--pin` for an openrouter
arm and rejects it for every other provider, and `pin` itself runs only for
an openrouter arm on an openrouter production, since it reads the endpoint
listing with the plugin key.

### 3. Ingest

```
scripts/model-eval.sh ingest <arm> --pin '["host/fp8", ...]'
scripts/model-eval.sh ingest <arm>
```

The first form is an openrouter arm; the second is any other provider.
Snapshots the running production container and its bank config into the run
directory, generates the eval compose file from that snapshot, recreates the
eval container on it, waits for health, proves the container serves this
arm's provider and model, and runs the parity check against the snapshot.
Parity prints `PASS` or `FAIL` with every difference named. A `FAIL` is a bug
in the generator, never a reason to widen the allow-list. Then it loads the
subset into a fresh bank named after the run, waits for the queue to drain,
checks the bank config against the snapshot again, and scores.

The run id is `<date>_<arm>_<image-tag>`, printed at the end. A second run of
the same arm on the same day gets a numbered suffix. No run ever overwrites
another, and a bank that already holds data is never ingested into again.

`--dry-run` stops after parity and retains nothing: it proves an arm boots
and matches production without spending, and leaves its artifacts in a
temporary directory it names. `--subset <file>` picks another id list from
`corpus/`; the default is the 52-memory `half.txt` every recorded run used.
Results on a different subset are not comparable to the recorded ones.

### 4. Local arms that need the machine to themselves

A local Ollama model can need every core and all the memory production is
holding. `--exclusive` stops production for the run and restarts it when the
run ends, on every exit path, success or failure:

```
scripts/model-eval.sh ingest <arm> --exclusive --key-is-for ollama
```

It applies only to an `ollama` arm. Before anything stops, the command says
what it is about to do and waits for the user to type `yes` on the terminal.
It refuses outright when there is no terminal to type on, or when
`ATK_NONINTERACTIVE=1` is set, so an unattended session can never stop
production. The yes must come from the user: tell them agents lose their
memory while production is down, and never type it on their behalf. Without
`--exclusive`, a local arm runs beside production.

An exclusive run is recorded as such, and its read side needs the machine
too: `read` on it requires `--exclusive` and goes through the same
confirmation and the same restart guarantee.

### 5. Read

```
scripts/model-eval.sh read <run-id>
```

Brings the container back up on the run's own provider, model and pin,
regenerated from the run's own production snapshot, checks parity against
that snapshot again, confirms the bank is as ingest left it, and runs recall,
reflect and two mental models. Queries target only memories the run ingested.
Mental models take a few minutes each; pass `--skip-mental-models` for a
quick look. `--key-is-for` applies exactly as for `ingest`.

### 6. Compare

```
scripts/model-eval.sh compare
scripts/model-eval.sh compare --runs <id>,<id>
scripts/model-eval.sh cost --runs <id>
```

`compare` puts every run side by side, oldest first, write side then read
side, with a legend mapping each column to its run id, provider and model. It
reads facts back from the eval instance, so the container must be up. `cost`
prices the bank's own LLM request log against the run's pinned hosts; it is
for openrouter runs on an openrouter production and says so otherwise. `list`
shows every run, its provider and model, and which steps it has completed.

### 7. Record

Retain a summary to memory, tagged with the project tag of the directory you
are working in, per the memory protocol: the provider, the model, the pin,
the image version, survival, recall@1 and recall@5 with the closest recorded
run beside them, the measured cost, the verdict, and the run directory. Date
it. A run that is not recorded is a run the next session cannot find.

## Reading the numbers

- **Survival first.** Below the high nineties on this corpus a model is
  dropping literals; the recorded cloud arms sit between 93.9% and 99.4%.
  `silent losses` above zero is a broken arm, not a weak one: read the failed
  operations before anything else.
- **Survival cannot rank models on its own.** Copying the source scores 100%.
  Read it beside `median copied` and `expansion`; a model far above the others
  on both is quoting, and its facts are worse retrieval targets.
- **recall@5 is the availability number; recall@1 is the ranking number.** A
  literal at rank 2 or 3 is one the agent still gets; a miss is one it never
  sees. When recall@1 drops but recall@5 holds, the targets slid down the
  ranking, which is demotion, not loss. Say which it is.
- **Observation crowding.** `observation share` is how much of every result
  list is consolidation output rather than source facts. A higher share with
  the same recall@5 and a lower recall@1 means observations are taking the top
  ranks from the facts that carry the literal.
- **Split the misses.** `never stored` is ingestion loss and belongs to the
  write side; `stored, unranked` is ranking loss. Different problems, different
  fixes.
- **Noise band.** The same model and pin re-run on a new image moved survival
  by 0.5 points and recall@1 by 2.6 points. Differences inside that band are
  not a ranking.
- **Strict against non-strict is not a ranking either.** A run flagged
  `strict_schema: false` measured JSON-mode extraction; read it against other
  non-strict runs, or say plainly that the comparison crosses that line.
- **Reflect and mental models are cost as much as quality.** Literal hit rate
  is the quality; input tokens and characters are what every load pays.

## Known limits

- **The corpus is frozen.** Its generator was not preserved. That is what keeps
  every run comparable to the recorded baselines, and it means the corpus
  cannot be extended. `corpus/SCORING_NOTES.md` holds the scoring rules that
  came out of building it. `corpus/queries.json` is the frozen query set;
  `scripts/retrieval_test.py --generate-only` reproduces it byte for byte.
- **An exclusive run refuses unattended.** It needs a yes typed on a terminal
  in the session that runs it, so it cannot be scheduled, backgrounded or run
  from an agent session without a terminal.
- **Results are per machine.** They live in the plugin's `custom/` area, which
  ATK keeps in its own git and out of the registry.
- **One eval container.** Runs are sequential; two at once would share a
  worker id and reclaim each other's tasks.
- **Runs recorded before snapshots existed carry none.** `compare`, `cost`
  and `list` still read them; `read` cannot re-run them, since there is no
  production state to check them against.

## When a step fails

- **`parity` says FAIL.** The generated stack differs from the snapshot outside
  the allow-list. Read the named difference and run `ingest` again, which
  snapshots and regenerates. Never edit the allow-list in `scripts/parity.py`
  or the generated compose file.
- **`ingest` or `read` stops at the key.** The arm's provider is not
  production's, so the plugin key does not fit. Follow the procedure under
  "Before you start": the user swaps `HINDSIGHT_LLM_API_KEY` in the plugin's
  `.env`, reruns with `--key-is-for`, and swaps it back afterwards. Do not
  look for a key anywhere else.
- **`--exclusive` is refused.** There is no terminal to type yes on, or
  `ATK_NONINTERACTIVE=1` is set. Run it from an interactive terminal; nothing
  else unlocks it.
- **`ingest` reports `NO DOCUMENT` or failed operations.** The retain never
  landed or extraction failed. Read the printed errors. A burst of `429`
  means a pinned host is rate limiting the shared pool, usually because
  production is busy on the same host; the eval already runs at production's
  concurrency and retries, so run again at a quieter time rather than moving
  to hosts production does not use. The run directory stays as evidence;
  start a new run rather than reusing it.
- **`ingest` times out draining.** `run.json` records `drained: false` and the
  queue state it reached. The run is incomplete; start a new one.
- **`read` says the bank is not on the eval instance.** The eval volume was
  replaced or the bank deleted. The run cannot be read; ingest again as a new
  run.
- **`compare` cannot reach the eval instance.** Bring it up with `read` on any
  run; copy ratios read the banks live.
- **`pin` proposes fewer than four hosts.** Fewer is fine, and the run records
  what it used. Zero means the model is not usable under strict schema on any
  acceptable host, which is itself the verdict.
