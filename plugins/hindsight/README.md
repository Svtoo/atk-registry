# Hindsight

Persistent memory for coding agents. The agent writes what it learns with
`retain`, pulls it back with `recall`, and asks `reflect` what is true now that
facts have changed over time. Runs in Docker on your machine, or you point it at
an instance someone else runs.

Upstream: [docs](https://hindsight.vectorize.io) ·
[configuration](https://hindsight.vectorize.io/developer/configuration) ·
[performance](https://hindsight.vectorize.io/developer/performance)

Needs atk 0.4.0 or newer.

## Connect to an instance someone else runs

```
atk add hindsight
atk setup hindsight          # HINDSIGHT_MODE=remote, HINDSIGHT_URL, HINDSIGHT_BANK
atk install hindsight        # checks the URL answers, applies the bank settings, tests the LLM
atk plug hindsight --claude
```

You get the MCP endpoint at `$HINDSIGHT_URL/mcp/$HINDSIGHT_BANK/` (streamable
HTTP, 10-minute tool timeout because `reflect` takes minutes) and `SKILL.md`,
the per-turn protocol the agent follows. Install and every start apply the
settings under "What ATK sets on the bank" to your bank on that instance;
`HINDSIGHT_RETAIN_MODE=off` and `HINDSIGHT_SEARCH_DIRECTIVE=off` leave it
alone.

Of the rest of this page, "What ATK sets on the bank", "Cost", "Mental models"
and the `banks`, `conform` and `mental-models` commands are yours too; they act
on your bank wherever it lives. Skip "Run it here", the container overrides, and
`backup`, `restore` and `schedule`, which manage a local database and refuse in
remote mode.

## Run it here

You need Docker Desktop, somewhere to run the extraction model (Ollama on this
machine, or any hosted OpenAI-compatible API and its key), and
[Ollama](https://ollama.com) with `mxbai-embed-large` pulled for embeddings.

```
atk add hindsight
atk setup hindsight
atk install hindsight        # checks Docker, Ollama and the models; pulls; starts; applies the bank settings; tests the LLM
atk plug hindsight --claude
```

Web UI at http://localhost:9999. API and MCP on 8888.

## Settings

`atk setup hindsight` asks for these.

| Setting | Default | What it does |
|---|---|---|
| `HINDSIGHT_MODE` | `local` | `local` runs the container here; `remote` uses `HINDSIGHT_URL` |
| `HINDSIGHT_URL` | `http://localhost:8888` | Where the API lives |
| `HINDSIGHT_BANK` | `default` | The one bank this agent reads and writes; the MCP endpoint cannot reach another. Tags organise inside a bank: no tag searches everything, one tag narrows to it plus untagged |
| `HINDSIGHT_LLM_PROVIDER` | none, required | `ollama` for this machine, or a hosted provider such as `openrouter`, `groq`, `openai`, `anthropic` |
| `HINDSIGHT_LLM_MODEL` | `z-ai/glm-5.3-flash` | Extracts facts, merges duplicates, answers `reflect`. Name is provider-specific |
| `HINDSIGHT_LLM_API_KEY` | `not-needed` | Ollama ignores it; `*:cloud` models use `ollama signin` |
| `HINDSIGHT_RETAIN_MODE` | `custom` | How much detail extraction keeps, see "What ATK sets on the bank" |
| `HINDSIGHT_BACKUP_DIR` | unset | Absolute path for backups; skipped while unset |

Everything else has a working default. To change one, add it to
`~/.atk/plugins/hindsight/.env` and `atk restart hindsight`. For anything the
variables do not reach, a `custom/docker-compose.override.yml` beside them is
merged in automatically.

| Override | Default | When |
|---|---|---|
| `HINDSIGHT_LLM_BASE_URL` | provider's own | A proxy, or Ollama on another host |
| `HINDSIGHT_EMBEDDING_MODEL` | `mxbai-embed-large` | Changing it after memories exist means re-embedding everything |
| `HINDSIGHT_EMBEDDING_DIMENSIONS` | `1024` | Must match the model |
| `HINDSIGHT_EMBEDDING_BASE_URL` / `_API_KEY` | host Ollama | Embeddings served elsewhere |
| `HINDSIGHT_RERANKER_PROVIDER` | `flashrank` | `local` ranks slightly better and costs far more CPU |
| `HINDSIGHT_RERANKER_MODEL` | `ms-marco-MiniLM-L-12-v2` | Another FlashRank model |
| `HINDSIGHT_RERANKER_LOCAL_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Another cross-encoder; keep it small, see "Model" |
| `HINDSIGHT_RERANKER_MAX_CANDIDATES` | `300` | Lower is faster and drops the tail of the pool before ranking |
| `HINDSIGHT_RERANKER_LOCAL_BUCKET_BATCHING` | `true` | Off restores upstream behaviour; on is faster with identical scores |
| `HINDSIGHT_LLM_REASONING_EFFORT` | `low` | Raise if the model needs thinking to return valid JSON |
| `HINDSIGHT_REFLECT_WALL_TIMEOUT` | `600` | Seconds for one `reflect`, which is what a mental-model refresh runs. Upstream's 300 fails real refreshes intermittently and silently |
| `HINDSIGHT_REFLECT_MAX_COMPLETION_TOKENS` | unset | Hard output cap on `reflect`, the only real cost ceiling. On thinking models it is spent on reasoning and truncates a page mid-word |
| `HINDSIGHT_LLM_STRICT_SCHEMA` | off | See "Model" |
| `HINDSIGHT_LLM_EXTRA_BODY` | `null` | Request-body JSON the provider accepts outside the OpenAI schema. Valid JSON or `null`, never empty |
| `HINDSIGHT_MCP_STATELESS` | `true` | `false` restores session MCP, and every restart then strands connected agents until they reconnect |
| `HINDSIGHT_VOLUME_NAME` | `hindsight_data` | Isolated instances side by side |

## Model

- It must return JSON rather than narrate, keep who did what to whom, and keep
  exact numbers. Any hosted provider, and an Ollama `:cloud` tag, sees every
  memory's full text.
- `HINDSIGHT_LLM_STRICT_SCHEMA=true` has the provider constrain decoding
  against the schema. Without it a malformed answer is a silently dropped
  write: the retain reports success and stores nothing. Most hosted
  OpenAI-compatible providers support it; a small local model behind Ollama
  usually does not. The container also accepts
  `HINDSIGHT_API_LLM_STRUCTURED_OUTPUT_FORCED_TOOL` and the per-operation
  `..._STRICT_SCHEMA_RETAIN`, `_REFLECT`, `_CONSOLIDATION` variants, not
  surfaced here.
- Judge a candidate on getting memories back, not only on writing them down.
  `skills/model-eval/SKILL.md` runs the bake-off against this stack.
- Keep the reranker small. The default is a ~90MB cross-encoder on CPU (Docker
  on macOS cannot reach the GPU); `BAAI/bge-reranker-v2-m3` took the container
  to 10.4GB and 800% CPU. `docker-compose.yml` caps it at 8GB and 4 CPUs.

## What ATK sets on the bank

Applied by `atk install hindsight` and on every start. ATK records what it
wrote, leaves a setting you changed in the UI alone, and
`atk run hindsight conform --force` takes it back.

- **Retain mode.** Upstream's `concise` drops identifiers, flags and commands.
  `custom` (the default) is concise plus `retain-instructions.md`; replace it
  via `custom/retain-instructions.md`, or set `concise`, `verbose`, `verbatim`,
  `chunks`, or `off`. The raw text of every memory is stored whatever the mode.
- **Search directive.** A bank directive named `search-coverage` makes every
  `reflect`, mental-model refreshes included, search each aspect the question
  names before it writes. Ships in `search-directive.md`; replace it via
  `custom/search-directive.md`; `HINDSIGHT_SEARCH_DIRECTIVE=off` removes it.

## Cost

Extraction is cheap. Spend concentrates in mental-model refreshes, which
re-synthesise a standing answer over the whole bank; one refresh can cost more
than a hundred retains.

- `refresh_cron` on each model is the main dial. Twice a week is generous.
- `delta` mode (the default) edits the stored document and skips a refresh
  when nothing new is in scope. `full` regenerates from scratch and drifts
  between runs even over an unchanged bank.
- A model's `max_tokens` is a target, not a cap.
  `HINDSIGHT_REFLECT_MAX_COMPLETION_TOKENS` is the only hard ceiling.

## Mental models

A standing answer to one question, refreshed on a schedule, read by agents
before they start. Write `source_query` as an open question, and keep scopes
disjoint. The MCP surface cannot set a schedule or mode, so create from the CLI:

```
atk run hindsight mental-models create writing-code \
  --query 'How does this user want code written and changed?' \
  --cron '0 17 * * 1,4'
```

## Commands

```
atk status|restart|logs|help hindsight
atk run hindsight banks [delete <bank>...]   # list banks, or delete with confirmation
atk run hindsight conform [--force]          # apply the bank settings above
atk run hindsight mental-models --help       # list, create, set, refresh, dry-run, audit, review, rebuild, delete
skills/model-eval/scripts/model-eval.sh      # bake off a candidate model; see skills/model-eval
atk run hindsight backup [--if-stale]        # pg_dump to HINDSIGHT_BACKUP_DIR, no downtime
atk run hindsight schedule [off|status]      # daily backup via launchd; macOS only, errors elsewhere
atk run hindsight restore [file]             # DESTRUCTIVE: replace the database from a dump
```

## Backups

`backup` writes a compressed `pg_dump` named
`hindsight_backup_<date>_<time>_hs<version>.dump`, where the version is what the
server reports, and verifies the archive's table of contents before promoting
it. `pg_restore --list` reads back the date it was taken, the database name and
the PostgreSQL version without needing a database.

Retention keeps the newest dump of each of the last 3 days, 2 ISO weeks and 2
months. The tiers overlap, so the folder settles at about five dumps. A run
killed mid-dump leaves a `.partial`, which the next run removes.

`schedule` installs a launchd job
(`com.atk.hindsight-backup`) that wakes hourly and dumps once the newest backup
is a day old. It is macOS only and says so anywhere else; elsewhere, run
`atk run hindsight backup --if-stale` hourly from cron or a systemd timer, which
is the same command the job runs. Failures raise a notification and land in
`~/Library/Logs/atk-hindsight-backup.log`. `restore` loads into a scratch
database first and swaps only after that succeeds; it always asks.

## When it breaks

Start with `atk logs hindsight`.

- Writes fail with a JSON decode error: the model narrates instead of returning
  JSON. Pick another, or turn on strict schema.
- Install says the provider rejected the key: the key is wrong, expired, or was
  never set, and nothing will be stored. Fix it with `atk setup hindsight`, then
  `atk install hindsight`, which tests it again. The test asks the server, which
  is the only party that knows every provider's credentials, and the answer it
  gives back is a status and nothing else.
- "A container cannot reach Ollama": Ollama is bound to 127.0.0.1. On macOS,
  `launchctl setenv OLLAMA_HOST 0.0.0.0:11434`, then restart it.
- "Model is not available": `ollama pull <model>`; `:cloud` also needs
  `ollama signin`.
- Nothing is ever recalled: `atk run hindsight banks` shows which bank holds
  the facts. A recall never crosses banks.
- Recall is slow or memory-hungry: the reranker note under "Model", then
  upstream's performance guide.

## Skills

Point your agent at the file.

- `SKILL.md`: the per-turn memory protocol; `atk plug` wires it in.
- `skills/migrate-openmemory/SKILL.md`: move an OpenMemory corpus across,
  keeping each memory's date. It pauses to have you map old project tags onto
  directories; a wrong mapping fails silently.
- `skills/model-eval/SKILL.md`: evaluate an extraction model on a frozen corpus
  against this stack.

## Ports

`8888` API and MCP (`/mcp/<bank>/`), `9999` web UI.
