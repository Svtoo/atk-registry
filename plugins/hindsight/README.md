# Hindsight

Persistent memory for coding agents. The agent writes what it learns with
`retain`, pulls it back with `recall`, and asks `reflect` what is true now that
facts have changed over time. Runs in Docker on your machine, or points at an
instance someone else runs.

Upstream: [docs](https://hindsight.vectorize.io) ·
[configuration](https://hindsight.vectorize.io/developer/configuration) ·
[performance](https://hindsight.vectorize.io/developer/performance)

Needs atk 0.4.0 or newer. The plugin lives at `~/.atk/plugins/hindsight/`;
every path below is relative to it.

## Install

```
atk add hindsight            # asks for the settings below, then installs
atk plug hindsight --claude  # or --codex, --gemini, --auggie, --opencode
```

- **Remote** (an instance someone else runs): set `HINDSIGHT_MODE=remote`,
  `HINDSIGHT_URL` and `HINDSIGHT_BANK`; leave the four local-only settings
  empty. Install checks the URL answers, applies the bank settings, tests the LLM.
- **Local**: Docker Desktop, somewhere to run the extraction model (Ollama here,
  or a hosted OpenAI-compatible API and its key), and [Ollama](https://ollama.com)
  with `mxbai-embed-large` pulled for embeddings. Install checks Docker, Ollama
  and the models, pulls, starts, applies the bank settings, tests the LLM.

You get the MCP endpoint `$HINDSIGHT_URL/mcp/$HINDSIGHT_BANK/` (streamable HTTP,
10-minute tool timeout because `reflect` takes minutes), the web UI on port 9999
of the same host, and `SKILL.md`, the per-turn protocol the agent follows.

## Settings

`atk add` and `atk setup hindsight` ask for these.

| Setting | Default | What it does |
|---|---|---|
| `HINDSIGHT_MODE` | `local` | `local` runs the container here; `remote` uses `HINDSIGHT_URL` |
| `HINDSIGHT_URL` | `http://localhost:8888` | Where the API lives |
| `HINDSIGHT_BANK` | `default` | The one bank this agent reads and writes; the MCP endpoint cannot reach another |
| `HINDSIGHT_LLM_PROVIDER` | none | Local only. `ollama` for this machine, or a hosted provider such as `openrouter`, `groq`, `openai`, `anthropic` |
| `HINDSIGHT_LLM_MODEL` | `z-ai/glm-5.3-flash` | Local only. Extracts facts, merges duplicates, answers `reflect`. Name is provider-specific |
| `HINDSIGHT_LLM_API_KEY` | `not-needed` | Local only. Ollama ignores it |
| `HINDSIGHT_RETAIN_MODE` | `custom` | How much detail extraction keeps, see "What ATK sets on the bank" |
| `HINDSIGHT_BACKUP_DIR` | unset | Local only. Absolute path for backups; skipped while unset |

Everything else has a working default. To change one, add it to `.env`, or for
anything the variables do not reach, to `custom/docker-compose.override.yml`,
then `atk restart hindsight`. Everything under `custom/` survives
`atk upgrade hindsight`; edits anywhere else do not.

Where this plugin departs from upstream, or a wrong value fails silently:

| Override | Default | When |
|---|---|---|
| `HINDSIGHT_LLM_BASE_URL` | provider's own | A proxy, or Ollama on another host |
| `HINDSIGHT_EMBEDDING_MODEL` | `mxbai-embed-large` | Changing it after memories exist means re-embedding everything |
| `HINDSIGHT_LLM_STRICT_SCHEMA` | off | See "Model" |
| `HINDSIGHT_LLM_REASONING_EFFORT` | `low` | Raise if the model needs thinking to return valid JSON |
| `HINDSIGHT_LLM_EXTRA_BODY` | `null` | Request-body JSON outside the OpenAI schema. Valid JSON or `null`, never empty |
| `HINDSIGHT_REFLECT_WALL_TIMEOUT` | `600` | Seconds for one `reflect`, which is what a mental-model refresh runs. Upstream's 300 fails real refreshes intermittently and silently |
| `HINDSIGHT_REFLECT_MAX_COMPLETION_TOKENS` | unset | Hard output cap on `reflect`. On thinking models it is spent on reasoning and truncates a page mid-word |
| `HINDSIGHT_RERANKER_LOCAL_BUCKET_BATCHING` | `true` | Off restores upstream behaviour; on is faster with identical scores |
| `HINDSIGHT_MCP_STATELESS` | `true` | `false` restores session MCP, and every restart then strands connected agents until they reconnect |
| `HINDSIGHT_SEARCH_DIRECTIVE` | `on` | `off` removes the search-coverage directive from the bank |
| `HINDSIGHT_VOLUME_NAME` | `hindsight_data` | Isolated instances side by side |

Every other variable the container accepts is in the upstream configuration page.

## Model

- It must return JSON rather than narrate, keep who did what to whom, and keep
  exact numbers. Any hosted provider, and an Ollama `:cloud` tag, sees every
  memory's full text.
- `HINDSIGHT_LLM_STRICT_SCHEMA=true` has the provider constrain decoding
  against the schema. Without it a malformed answer is a silently dropped
  write: the retain reports success and stores nothing. Most hosted
  OpenAI-compatible providers support it; a small local model behind Ollama
  usually does not.
- Judge a candidate on getting memories back, not only on writing them down.
  `skills/model-eval/SKILL.md` runs the bake-off against this stack.
- Keep the reranker small. The default is a ~90MB cross-encoder on CPU (Docker
  on macOS cannot reach the GPU); `BAAI/bge-reranker-v2-m3` took the container
  to 10.4GB and 800% CPU. `docker-compose.yml` caps it at 8GB and 4 CPUs.

## What ATK sets on the bank

Applied by install and on every start, in both modes. ATK records what it wrote
in `custom/.conform-state/`, leaves a setting you changed in the UI alone, and
`atk run hindsight conform --force` takes it back.

- **Retain mode.** Upstream's `concise` drops identifiers, flags and commands.
  `custom` (the default) is concise plus `retain-instructions.md`; replace it
  via `custom/retain-instructions.md`, or set `concise`, `verbose`, `verbatim`,
  `chunks`, or `off`. The raw text of every memory is stored whatever the mode.
- **Search directive.** A bank directive named `search-coverage` makes every
  `reflect`, mental-model refreshes included, search each aspect the question
  names before it writes. Ships in `search-directive.md`; replace it via
  `custom/search-directive.md`; `HINDSIGHT_SEARCH_DIRECTIVE=off` removes it.
- **MCP tool list.** The bank exposes only the tools `SKILL.md` teaches the
  agent to call; this is what narrows an instance someone else hosts. Change it
  in the UI and ATK leaves it alone; to set it permanently, list one tool per
  line in `custom/mcp-tools.txt`.

## Mental models and cost

Extraction is cheap. Spend concentrates in mental-model refreshes, which
re-synthesise a standing answer over the whole bank; one refresh can cost more
than a hundred retains.

- `refresh_cron` on each model is the main dial. Twice a week is generous.
- `delta` mode (the default) edits the stored document and skips a refresh
  when nothing new is in scope. `full` regenerates from scratch and drifts
  between runs even over an unchanged bank.
- A model's `max_tokens` is a target, not a cap.
  `HINDSIGHT_REFLECT_MAX_COMPLETION_TOKENS` is the only hard ceiling.

The MCP surface cannot set a schedule or mode, so create from the CLI:

```
atk run hindsight mental-models create writing-code \
  --query 'How does this user want code written and changed?' \
  --cron '0 17 * * 1,4'
```

## Commands

```
atk status|restart|logs|help hindsight       # logs: local only
atk upgrade hindsight                        # keeps custom/
atk remove hindsight                         # asks before deleting the memories volume
atk run hindsight banks [delete <bank>...]   # list banks, or delete with confirmation
atk run hindsight conform [--force]          # apply the bank settings above
atk run hindsight mental-models -- --help    # models, schedules and modes the MCP surface cannot set
atk run hindsight backup [--if-stale]        # local only: pg_dump to HINDSIGHT_BACKUP_DIR, no downtime
atk run hindsight schedule [off|status]      # local only: daily backup via launchd, macOS
atk run hindsight restore [file]             # local only, DESTRUCTIVE: replace the database from a dump
```

For an agent: `rebuild` and `delete` take `--yes`, `dry-run` takes `--json`.

## Backups (local only)

Set `HINDSIGHT_BACKUP_DIR` or backup is skipped. Each dump is named with its
date and the Hindsight version; retention keeps the newest of the last 3 days,
2 weeks and 2 months, about five dumps. `schedule` is macOS only; elsewhere run
`atk run hindsight backup --if-stale` hourly from cron or a timer. `restore`
loads into a scratch database first, swaps only after that succeeds, and always
asks. The rest is in each command's `--help`.

## When it breaks

Start with `atk logs hindsight` (local only; a remote instance keeps its own).

- Writes fail with a JSON decode error: the model narrates instead of returning
  JSON. Pick another, or turn on strict schema.
- Install says the provider rejected the key: the key is wrong, expired, or was
  never set, and nothing will be stored. `atk setup hindsight`, then
  `atk install hindsight`, which tests it again.
- "A container cannot reach Ollama" (local): Ollama is bound to 127.0.0.1. On
  macOS, `launchctl setenv OLLAMA_HOST 0.0.0.0:11434`, then restart it.
- "Model is not available" (local): `ollama pull <model>`; `:cloud` also needs
  `ollama signin`.
- Nothing is ever recalled: `atk run hindsight banks` shows which bank holds
  the facts. A recall never crosses banks.
- Recall is slow or memory-hungry: see "Model", then upstream's performance guide.

## Files

- `.env`: the settings above.
- `custom/`: your overrides; the only directory `atk upgrade` preserves.
- `docker-compose.yml`: the container, its resource caps and defaults.
- `SKILL.md`: the per-turn memory protocol the agent runs.
- `skills/migrate-openmemory/SKILL.md`: move an OpenMemory corpus across,
  keeping each memory's date. It pauses to have you map old project tags onto
  directories; a wrong mapping fails silently.
- `skills/model-eval/SKILL.md`: evaluate an extraction model on a frozen corpus
  against this stack.
