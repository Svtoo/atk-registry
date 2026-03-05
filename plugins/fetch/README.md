# fetch

Web content fetching via MCP — retrieve any URL and receive clean Markdown output optimised for LLM analysis and quoting.

## Overview

`mcp-server-fetch` is an official Model Context Protocol server maintained by the MCP org. It fetches URLs over the
internet and converts HTML to Markdown, making web content token-efficient and easy for LLMs to quote and reason over.
Content is returned in chunks via `start_index` so long pages can be paginated without hitting context limits.

> ⚠️ **Security note**: this server can reach local/internal IP addresses. Only enable it in trusted environments.

## Installation

Requires: [uv](https://docs.astral.sh/uv/) (install with `brew install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`)

```bash
atk add fetch
```

No credentials required — the server works without any configuration.

## Environment Variables

| Variable     | Default | Description                                                                 |
|--------------|---------|-----------------------------------------------------------------------------|
| `USER_AGENT` | —       | Custom User-Agent string. Leave unset for the default MCP user-agent.       |

## Usage

```bash
# Show MCP configuration (for use with Claude Desktop, VS Code, etc.)
atk mcp show fetch

# Show raw JSON configuration
atk mcp show fetch --json
```

The plugin exposes a single MCP tool. Point your MCP client at the `fetch` server and call the `fetch` tool with any URL.

## MCP Tools

Verified against live server (`mcp-server-fetch` v1.26.0):

- **fetch**: Fetches a URL from the internet and optionally extracts its contents as markdown.
  - `url` (string, required): URL to fetch
  - `max_length` (integer, optional, default 5000): Maximum number of characters to return
  - `start_index` (integer, optional, default 0): Start content from this character index (useful for paginating long pages)
  - `raw` (boolean, optional, default false): Return raw HTML instead of simplified Markdown

## Links

- [Upstream repository](https://github.com/modelcontextprotocol/servers/tree/main/src/fetch)
- [Model Context Protocol](https://modelcontextprotocol.io)

