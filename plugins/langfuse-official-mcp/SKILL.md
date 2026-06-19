# Langfuse Official MCP — Skill

This MCP talks to the official Langfuse server (`<host>/api/public/mcp`) for the user's Langfuse
project — LLM observability, prompt management, evaluation, and analytics. Use it to inspect and
manage Langfuse data without leaving the agent.

## Tools

Tools are grouped by Langfuse resource (exact names visible via the client's tool list):

- **Prompts** — `getPrompt`, `listPrompts`, `createTextPrompt`, `createChatPrompt`,
  `updatePromptLabels`. Fetch a prompt by name/label, list versions, create or relabel prompts.
- **Observations** — list/get spans, generations, and events for a trace.
- **Metrics** — `queryMetrics` for aggregate cost/latency/usage/volume/score analytics;
  `getMetricsSchema` / `getObservationFilterSchema` to discover queryable dimensions and filters
  before composing a query.
- **Scores** — read/create scores and score configs (eval results attached to traces/observations).
- **Datasets** — datasets, items, runs, run-items (offline eval test cases and experiment runs).
- **Comments, annotation queues, evaluators, models, media, health** — supporting resources.

## When to use it

- Pulling traces/scores for a session, reading eval results, or comparing prompt versions
  interactively.
- Managing prompts (fetch/list/create/relabel) from the agent.
- Ad-hoc analytics via `queryMetrics` (always call the schema-introspection tool first).

## When NOT to use it

- For **programmatic** pipelines that pull traces, push dataset items, or post scores in bulk,
  prefer the Langfuse Python/JS SDK or REST API directly — broader, more reliable, no bridge hop.
  This MCP is a thin layer over that same API and adds no capability the SDK lacks.

## Notes

- **Discover before querying metrics:** call `getMetricsSchema` / `getObservationFilterSchema`
  first; `queryMetrics` is Beta, defaults to a 100-row limit, and rejects grouping by
  high-cardinality dimensions (user, session).
- **Writes are enabled by default** (create/update prompts, scores, datasets, comments). Be
  deliberate with anything that mutates the user's Langfuse project.
- The data visible is scoped to the project whose keys are configured.
