# Notion MCP Plugin for ATK

Notion integration via MCP — search pages, read and write content, manage databases, and keep documentation in sync.

## Overview

This plugin wraps [Notion's official MCP server](https://github.com/makenotion/notion-mcp-server) to give AI agents
access to the Notion API through the Model Context Protocol. It supports searching, reading, and writing pages and
databases using an internal integration token.

## Installation

Requires: [Node.js / npx](https://nodejs.org/) (available in PATH)

```bash
atk add notion
```

You will be prompted for your `NOTION_TOKEN`. This is your Notion internal integration token.

### Creating a Notion Integration Token

1. Go to [https://www.notion.so/profile/integrations](https://www.notion.so/profile/integrations)
2. Click **New integration** (or select an existing one)
3. Under **Capabilities**, enable **Read content** and **Update content**
4. Copy the token (starts with `ntn_`)
5. Grant the integration access to your pages: visit each page → ⋯ menu → **Connect to integration**

## Environment Variables

| Variable       | Default | Description                                                                                    |
|----------------|---------|------------------------------------------------------------------------------------------------|
| `NOTION_TOKEN` | —       | **Required.** Notion internal integration token (starts with `ntn_`). Create at [notion.so/profile/integrations](https://www.notion.so/profile/integrations). |

## Usage

Get the MCP configuration for your client:

```bash
atk mcp show notion
atk mcp show notion --json
```

This plugin has no background service — `atk status notion` shows `mcp-only`, which is correct.

## MCP Tools

### Search & Users
- `API-post-search` — Search pages and data sources by title across your workspace
- `API-get-user` — Retrieve a specific user by ID
- `API-get-users` — List all users in the workspace
- `API-get-self` — Retrieve the bot user for the current integration token

### Pages
- `API-retrieve-a-page` — Retrieve a page and its properties
- `API-post-page` — Create a new page under a parent page or data source
- `API-patch-page` — Update page properties (title, status, etc.)
- `API-retrieve-a-page-property` — Retrieve a specific property item from a page
- `API-move-page` — Move a page to a different parent location

### Blocks (Page Content)
- `API-get-block-children` — Retrieve child blocks of a page or block (reads page content)
- `API-patch-block-children` — Append new blocks to a page or block (writes page content)
- `API-retrieve-a-block` — Retrieve a specific block by ID
- `API-update-a-block` — Update the content of a specific block
- `API-delete-a-block` — Delete a block

### Data Sources (Databases)
- `API-query-data-source` — Query a data source (database) with filters and sorts
- `API-retrieve-a-data-source` — Get metadata and schema for a data source
- `API-update-a-data-source` — Update data source properties
- `API-create-a-data-source` — Create a new data source
- `API-list-data-source-templates` — List available templates in a data source
- `API-retrieve-a-database` — Retrieve a database and its data source IDs

### Comments
- `API-retrieve-a-comment` — Retrieve comments on a page or block
- `API-create-a-comment` — Create a comment on a page or block

## Links

- [Notion MCP Server (GitHub)](https://github.com/makenotion/notion-mcp-server)
- [Notion API Reference](https://developers.notion.com/reference/intro)
- [Notion MCP Documentation](https://developers.notion.com/docs/mcp)
- [Creating Notion Integrations](https://www.notion.so/profile/integrations)

