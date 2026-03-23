# Streamlinear

Token-efficient Linear MCP for AI agents — one tool, seven actions, ~500 tokens vs ~17,000 for the official Linear MCP.

## Overview

[Streamlinear](https://github.com/obra/streamlinear) is a lightweight Linear integration for AI coding agents.
Instead of 23 separate tools, it exposes a single `linear` tool with action dispatch. Teams and workflow states
are fetched at startup and injected into the tool description, so agents always have current context.

## Installation

Requires: [Node.js / npx](https://nodejs.org/) (available in PATH)

```bash
atk add streamlinear
```

You will be prompted for your `LINEAR_API_TOKEN`.

### Getting a Linear API Token

1. Go to [https://linear.app](https://linear.app) → **Settings** → **Security and Access** → **Personal API keys**
2. Click **Create key**, give it a name (e.g. "AI agent")
3. Copy the token — it starts with `lin_api_`

## Environment Variables

| Variable            | Default | Description                                                                                     |
|---------------------|---------|-------------------------------------------------------------------------------------------------|
| `LINEAR_API_TOKEN`  | —       | **Required.** Linear personal API token (format `lin_api_xxxxx`). Create at linear.app settings. |

## Usage

This plugin has no background service — `atk status streamlinear` shows `mcp-only`, which is correct.

Get MCP configuration for your client:

```bash
atk mcp show streamlinear
atk mcp show streamlinear --json
atk mcp add streamlinear --claude --codex --gemini --auggie --opencode
```

## MCP Tools

The server exposes a single tool: **`linear`**

All operations are dispatched via the `action` field:

| Action     | Purpose                                                      | Example                                                        |
|------------|--------------------------------------------------------------|----------------------------------------------------------------|
| `search`   | Find issues (default: your assigned open issues)            | `{"action": "search"}`                                         |
| `get`      | Fetch issue by identifier, URL, or UUID                     | `{"action": "get", "id": "ENG-123"}`                           |
| `update`   | Change state, priority, or assignee on an issue             | `{"action": "update", "id": "ENG-123", "state": "Done"}`       |
| `comment`  | Add a comment to an issue                                   | `{"action": "comment", "id": "ENG-123", "body": "Fixed!"}`     |
| `create`   | Create a new issue (requires title + team identifier)       | `{"action": "create", "title": "Bug", "team": "ENG"}`          |
| `graphql`  | Raw Linear GraphQL passthrough for advanced queries         | `{"action": "graphql", "graphql": "query { viewer { name } }"}` |
| `help`     | Returns full inline documentation                           | `{"action": "help"}`                                           |

### Smart Defaults

- `search` with no parameters → returns the authenticated user's assigned, non-completed issues
- State names are fuzzy-matched: `"done"` matches `"Done"`, `"in prog"` matches `"In Progress"`
- IDs accept `ABC-123` identifiers, Linear URLs, or UUIDs
- `assignee: "me"` resolves to the authenticated user
- Teams and workflow states are shown in the tool description (fetched at startup)

### Known Behavior

- If `LINEAR_API_TOKEN` is unset or invalid, the server exits immediately with an error message
- The package is fetched directly from GitHub (`github:obra/streamlinear`) — no npm registry, no version pinning;
  this is intentional by the upstream author

## Links

- [Streamlinear on GitHub](https://github.com/obra/streamlinear)
- [Linear API Keys](https://linear.app/settings/api)
- [Linear GraphQL API](https://developers.linear.app/docs/graphql/working-with-the-graphql-api)

