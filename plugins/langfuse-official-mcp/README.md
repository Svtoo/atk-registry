# Langfuse Official MCP

The official Langfuse MCP server — query and manage prompts, traces, observations, scores,
datasets, and metrics — bridged into stdio for local AI agents.

## Overview

Langfuse ships a **native MCP server built into the platform**, reachable at
`<host>/api/public/mcp` over Streamable HTTP. As of the 2026-05-29 update it covers most of the
platform API (~15 tool categories: prompts, observations, metrics, scores, datasets, comments,
annotation queues, evaluators, models, media, health) — not just prompt management as in the
original 2025 release.

This plugin bridges that endpoint into stdio via `npx -y mcp-remote`, authenticating with HTTP
Basic built from your Langfuse public + secret keys. It is **distinct** from the `langfuse`
plugin, which provisions a self-hosted Langfuse instance; this one only adds the MCP client and
talks to whichever Langfuse (cloud or self-hosted) your keys belong to.

The MCP is a thin layer over the [Langfuse public REST API](https://langfuse.com/docs/api-and-data-platform/features/public-api) —
it grants no capability the API lacks. Prefer it for interactive/agentic exploration; for robust
programmatic access the Python/JS SDKs remain the workhorse.

## Installation

Requires: [Node.js / npx](https://nodejs.org/) and network access to your Langfuse host.

```bash
atk add langfuse-official-mcp
```

You'll be prompted for `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_HOST`
(Project Settings → API Keys in the Langfuse UI).

## Environment Variables

| Variable              | Default                       | Description                                                              |
|-----------------------|-------------------------------|--------------------------------------------------------------------------|
| `LANGFUSE_PUBLIC_KEY` | —                             | Project public key, `pk-lf-...` (required).                              |
| `LANGFUSE_SECRET_KEY` | —                             | Project secret key, `sk-lf-...` (required, secret).                      |
| `LANGFUSE_HOST`       | `https://us.cloud.langfuse.com` | Base URL. US cloud by default; use `https://cloud.langfuse.com` (EU), a regional host, or your self-hosted URL. **Keys are region-scoped** — the host must match your project's region. |

## Usage

This plugin has no background service — `atk status langfuse-official-mcp` shows `mcp-only`,
which is correct.

```bash
atk mcp langfuse-official-mcp             # show MCP config for manual wiring
atk plug langfuse-official-mcp --claude   # wire into Claude Code (also: --codex / --gemini / --auggie / --opencode)
```

To print the resolved bridge command without connecting (dummy values are fine — all three vars
are required):

```bash
LANGFUSE_MCP_DRYRUN=1 LANGFUSE_PUBLIC_KEY=pk LANGFUSE_SECRET_KEY=sk \
  LANGFUSE_HOST=https://us.cloud.langfuse.com bash mcp.sh
```

## MCP Tools

The server exposes **61 tools** (verified against the live server on 2026-06-19) across these
categories (authoritative live inventory: [mcp.reference.langfuse.com](https://mcp.reference.langfuse.com/)):

| Category          | Example tools                                                       |
|-------------------|---------------------------------------------------------------------|
| Prompts           | `getPrompt`, `listPrompts`, `createTextPrompt`, `updatePromptLabels` |
| Observations      | observation list / get (spans, generations, events)                 |
| Metrics/Analytics | `queryMetrics`, `getMetricsSchema`, `getObservationFilterSchema`     |
| Scores            | score + score-config create / list                                  |
| Datasets          | datasets, items, runs, run-items                                    |
| Comments          | create / list comments                                              |
| Annotation queues | queue items + assignments                                           |
| Evaluators/Models | evaluator rules, model definitions                                  |
| Media / Health    | media upload, health check                                          |

Both **read and write** tools are exposed by default; restrict to read-only via your MCP client's
allowlist.

## Notes

- **Secrets stay in `.env`:** the wrapper reads `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` /
  `LANGFUSE_HOST` from this plugin's `.env` at runtime — they are **not** injected into the agent's
  MCP config, so they never appear in `atk mcp` output or `claude mcp get`. `.env` is the single
  source of truth: edit it with `atk setup` and restart the agent (no re-plug needed); its values
  also override anything an agent snapshotted at plug time.
- **Self-hosted caveat:** the broad tool surface depends on the v2 Metrics/Observations APIs,
  which were Langfuse-Cloud-only as of late 2025 (self-hosted migration pending). If `LANGFUSE_HOST`
  points at a self-hosted instance, confirm it exposes `/api/public/mcp` and the v2 APIs.
- **Auth header:** mcp-remote receives `--header "Authorization: Basic <base64(pk:sk)>"`. If the
  server rejects it, confirm the keys belong to the target host and that the host has the MCP
  endpoint enabled.
- ATK's plugin schema supports `stdio` and `sse` transports; Langfuse speaks Streamable HTTP, so
  this plugin bridges via `npx -y mcp-remote` over stdio (same pattern as the `exa` plugin).

## Links

- [Langfuse MCP server docs](https://langfuse.com/docs/api-and-data-platform/features/mcp-server)
- [Live tool reference](https://mcp.reference.langfuse.com/)
- [Langfuse public REST API](https://langfuse.com/docs/api-and-data-platform/features/public-api)
- [Langfuse](https://langfuse.com/)
