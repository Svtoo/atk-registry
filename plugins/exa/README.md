# Exa

Neural web search and clean-markdown fetch for AI agents — via [Exa](https://exa.ai/)'s remote
MCP server.

## Overview

Exa is a search engine built for LLMs: neural embeddings instead of keyword match, full content
excerpts instead of snippets, and its own crawl/index instead of wrapping Google or Bing.

This plugin bridges Exa's remote MCP server (`https://mcp.exa.ai/mcp`) into stdio via
`mcp-remote`. Two tools — `web_search_exa` and `web_fetch_exa`. Works against the free tier with
no signup; provide an `EXA_API_KEY` for higher rate limits.

## Installation

Requires: [Node.js / npx](https://nodejs.org/) and network access to `mcp.exa.ai`.

```bash
atk add exa
```

You'll be prompted for `EXA_API_KEY` — leave blank to use the free tier.

## Environment Variables

| Variable      | Default | Description                                                                                                  |
|---------------|---------|--------------------------------------------------------------------------------------------------------------|
| `EXA_API_KEY` | —       | Optional. Provide for higher rate limits. Create one at [dashboard.exa.ai/api-keys](https://dashboard.exa.ai/api-keys). |

## Usage

This plugin has no background service — `atk status exa` shows `mcp-only`, which is correct.

```bash
atk mcp exa            # show MCP config for manual wiring
atk plug exa --claude  # wire into Claude Code (also: --codex / --gemini / --auggie / --opencode)
```

## MCP Tools

| Tool             | Purpose                                                                                          |
|------------------|--------------------------------------------------------------------------------------------------|
| `web_search_exa` | Neural web search. Returns content excerpts, not just snippets. Params: `query`, `numResults`.   |
| `web_fetch_exa`  | Fetch one or more URLs as clean Markdown. Params: `urls[]`, `maxCharacters` (default 3000).      |

### Query directives

The parameter surface is intentionally minimal — advanced behaviour goes in the query string:

- `category:company <query>` — returns company-profile-formatted results (employees, LinkedIn,
  traffic, growth).
- `category:people <query>` — returns LinkedIn-style people profiles.
- Including a URL in the query biases retrieval toward similar content — a degraded but useful
  version of the legacy `find_similar` endpoint.

## Notes

- The remote MCP exposes only `web_search_exa` and `web_fetch_exa`. Legacy tools (`find_similar`,
  `websets`, `company_research`, `deep_researcher_*`) are deprecated; their functionality lives
  partly in the query directives above, and fully in Exa's direct REST API.
- ATK's plugin schema today supports `stdio` and `sse` transports. Exa's endpoint speaks
  Streamable HTTP, so the plugin bridges via `npx -y mcp-remote` over stdio.

## Links

- [Exa](https://exa.ai/)
- [Exa MCP documentation](https://exa.ai/docs/reference/exa-mcp)
- [Exa MCP server source](https://github.com/exa-labs/exa-mcp-server)
- [Exa REST API](https://exa.ai/docs/reference/getting-started) (for the deprecated endpoints)
