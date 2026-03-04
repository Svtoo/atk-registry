# GitLab MCP Plugin for ATK

Search projects, issues and merge requests, read files, and automate common GitLab workflows from any MCP-compatible AI assistant.

## Overview

This plugin connects to the official [GitLab Duo MCP server](https://docs.gitlab.com/user/gitlab_duo/model_context_protocol/mcp_server/)
via the Model Context Protocol. It lets AI agents browse your GitLab projects, read source files, manage issues and
merge requests, without leaving the chat.

MCP-only plugin — no background service, no Docker, no ports. Configure once, use from your AI client.

> **Requires a paid GitLab plan.**
> The GitLab MCP server is only available on **Premium or Ultimate** tiers with **GitLab Duo** enabled.
> Free-tier accounts will get a `404 Not Found` error. See
> [GitLab Duo prerequisites](https://docs.gitlab.com/user/gitlab_duo/#prerequisites) for details.

Authentication is handled via **OAuth 2.0 browser flow** on first connect — no personal access token required.
On first use, your MCP client will open a browser window for you to authorize with your GitLab account.

## Prerequisites

- [Node.js](https://nodejs.org/) 20+ (provides `npx`)
- **GitLab 18.3 or later** (18.6+ recommended) — the MCP server was introduced as an experiment in
  GitLab 18.3 (feature flags disabled by default) and reached beta in GitLab 18.6 (feature flags
  removed). Self-hosted instances on GitLab 17.x or earlier cannot use this plugin.
- A GitLab account with [GitLab Duo](https://docs.gitlab.com/user/gitlab_duo/) enabled (Premium or Ultimate tier)
- Beta and experimental features turned on in GitLab Duo settings

## Installation

```bash
atk add gitlab
```

ATK will optionally prompt for a custom GitLab URL (leave blank for gitlab.com).

## Environment Variables

| Variable     | Default              | Description                                                     |
|--------------|----------------------|-----------------------------------------------------------------|
| `GITLAB_URL` | `https://gitlab.com` | Base URL — set to your instance URL if self-hosted GitLab       |

To update variables after installation:

```bash
atk setup gitlab
```

## Usage

After adding the plugin, get the MCP configuration for your client:

```bash
atk mcp show gitlab
atk mcp show gitlab --json   # raw JSON for Claude Desktop / Cursor
```

On first connection, your MCP client will open a browser for OAuth authorization. Approve the request to complete setup.

### MCP Capabilities

The GitLab MCP server (Beta) exposes tools for:

- **Projects**: browse, search, and read project metadata
- **Issues**: list, create, and update issues
- **Merge requests**: list, create, and inspect merge requests
- **Repository files**: read file contents and directory listings

The exact tool names are managed by GitLab and may change between server versions.
See the [official documentation](https://docs.gitlab.com/user/gitlab_duo/model_context_protocol/mcp_server/) for the authoritative tool list.

## Links

- [GitLab Duo MCP server documentation](https://docs.gitlab.com/user/gitlab_duo/model_context_protocol/mcp_server/)
- [GitLab Duo prerequisites](https://docs.gitlab.com/user/gitlab_duo/#prerequisites)
- [Model Context Protocol](https://modelcontextprotocol.io)

