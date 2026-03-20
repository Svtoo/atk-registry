# Metabase MCP Plugin for ATK

Metabase integration via MCP — list databases, run saved questions, execute SQL, explore schemas, manage dashboards, and browse collections.

## Overview

This plugin wraps [CognitionAI's Metabase MCP server](https://github.com/CognitionAI/metabase-mcp-server)
to give AI agents access to a self-hosted or cloud Metabase instance via its REST API. It exposes 21 tools
covering dashboards, cards/questions, databases, tables, collections, search, and SQL execution.

## Installation

Requires: [Node.js / npx](https://nodejs.org/) (available in PATH)

```bash
atk add metabase
```

You will be prompted for `METABASE_URL` and optionally `METABASE_API_KEY` (recommended) or
`METABASE_USERNAME` / `METABASE_PASSWORD` (fallback).

## Authentication

**API key (recommended — Metabase v0.46+):**

1. Open your Metabase instance → click your avatar → **Account Settings** → **API Keys** → **New key**
2. Copy the key and provide it as `METABASE_API_KEY` when prompted during `atk add`

**Username/password (fallback for Metabase < v0.46):**

Set `METABASE_USERNAME` and `METABASE_PASSWORD` instead. You can configure them with:
```bash
atk setup metabase
```

**Precedence:** If both `METABASE_API_KEY` and `METABASE_USERNAME` are set, the server uses the API key.

## Environment Variables

| Variable              | Required | Default | Description                                                                                   |
|-----------------------|----------|---------|-----------------------------------------------------------------------------------------------|
| `METABASE_URL`        | ✅ yes   | —       | Full URL to your Metabase instance. No trailing slash. E.g. `https://metabase.example.com` or `https://your-org.metabaseapp.com` (Metabase Cloud). |
| `METABASE_API_KEY`    | no       | —       | API key (preferred auth). Requires Metabase v0.46+. Obtain at Account Settings → API Keys.   |
| `METABASE_USERNAME`   | no       | —       | Login email — alternative auth for instances without API key support.                        |
| `METABASE_PASSWORD`   | no       | —       | Login password — required when using username/password auth.                                 |

> **Metabase Cloud**: Your URL is typically `https://your-org.metabaseapp.com`. API key auth works the same way.

> **Trailing slash warning**: `METABASE_URL` must not end with `/`. The server does not normalise it —
> a trailing slash will cause all API requests to fail with 404.

## Usage

```bash
# Show MCP configuration for your client
atk mcp show metabase
atk mcp show metabase --json

# Reconfigure credentials
atk setup metabase

# View logs (useful for auth debugging)
atk logs metabase
```

This plugin has no background service — `atk status metabase` shows `mcp-only`, which is correct.

## MCP Tools

The default (essential) tool set — loaded by `npx @cognitionai/metabase-mcp-server` with no flags:

### Dashboards
- `list_dashboards` — List all dashboards; use to discover analytical content
- `get_dashboard` — Get dashboard details by ID (cards, layout, settings)
- `get_dashboard_cards` — List all cards inside a specific dashboard
- `get_dashboard_related` — Find content related to a dashboard
- `get_dashboard_revisions` — Review dashboard revision history
- `create_dashboard` — Create a new dashboard in a collection

### Cards / Questions
- `list_cards` — List all saved questions/cards (optionally filter by type/model)
- `get_card` — Get metadata and query definition for a specific card
- `execute_card` — Run a saved card and return its current data
- `export_card_result` — Execute a card and export results (CSV, XLSX, JSON, etc.)
- `get_card_dashboards` — Find which dashboards contain a given card

### Databases
- `list_databases` — List all connected database sources
- `get_database` — Get connection details and schema info for a database
- `execute_query` — Run raw SQL against a connected database

### Tables
- `list_tables` — List tables (optionally filter by IDs)
- `get_table` — Get table schema, fields, and metadata

### Collections
- `list_collections` — List all Metabase collections (folders)
- `get_collection_items` — List cards and dashboards inside a collection

### Search & Other
- `search_content` — Search across all Metabase content (cards, dashboards, collections)
- `list_users` — List all users and their roles
- `get_metabase_playground_link` — Generate an interactive playground link for a SQL query

> The server also supports `--all`, `--read`, and `--write` flags for extended tool sets (80+ tools total).
> To use a specific mode, configure `METABASE_MCP_FLAGS` or adjust the `atk mcp` command args via
> `~/.atk/plugins/metabase/custom/overrides.yaml`.

## Links

- [Metabase MCP Server (GitHub)](https://github.com/CognitionAI/metabase-mcp-server)
- [Metabase API Keys documentation](https://www.metabase.com/docs/latest/people-and-org/api-keys)
- [Metabase Cloud](https://www.metabase.com/cloud)

