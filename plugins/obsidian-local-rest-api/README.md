# Obsidian Local REST API (with MCP)

Read, search, and edit your Obsidian vault from an AI agent, via the official
**"Local REST API with MCP"** community plugin's built-in MCP server.

## Overview

[Local REST API with MCP](https://github.com/coddingtonbear/obsidian-local-rest-api)
is an Obsidian plugin (by Adam Coddington) that exposes your vault over a secure,
locally-running HTTP API and a Model Context Protocol (MCP) server at `/mcp/`.

This ATK plugin bridges that MCP server to stdio so any MCP-capable agent
(Claude Code, etc.) can talk to it. It uses [`mcp-remote`](https://www.npmjs.com/package/mcp-remote)
under the hood and authenticates with the plugin's API key as a Bearer token.

The bridge is **secret-safe**: the API key lives only in this plugin's `.env`
(read by the wrapper at runtime) and is never written into the agent's MCP config,
so it won't appear in `atk mcp show` / `claude mcp get` output.

## Prerequisites

- **Obsidian** running, with the **Local REST API with MCP** plugin installed and
  enabled (this plugin was verified against upstream **v4.1.3**). The MCP server
  (`/mcp/`) is available in the 4.x line.
- **Node.js** (provides `npx`, which fetches `mcp-remote` on first run).
- Your **API key**, from Obsidian → Settings → Local REST API → *"Your API Key"*.

## Installation

```bash
atk add obsidian-local-rest-api
# or, from a local checkout of this registry:
atk add ./plugins/obsidian-local-rest-api
```

During `atk add` you'll be asked three things:

1. **`OBSIDIAN_API_KEY`** — your Local REST API key. Paste it (see *Getting your
   API key* below). No default — this is the only value you must supply.
2. **`OBSIDIAN_HOST`** — base URL of the server. Default `https://127.0.0.1:27124`
   is correct for a standard local Obsidian install; change it only if you moved
   the plugin's port or run Obsidian on another machine.
3. **`OBSIDIAN_VERIFY_TLS`** — TLS certificate verification. Default `false` is
   correct (the plugin's cert is self-signed); set `true` only if you've trusted
   that cert yourself.

### Getting your API key

1. In Obsidian, open **Settings** (⌘,) → **Community plugins** → **Local REST API**
   (click its gear / *Options*).
2. Near the top you'll see your **API key** (also shown inside a `Bearer …` box).
   Copy it and paste it at the prompt.

You can paste the bare key *or* the whole `Bearer …` line — the wrapper strips a
leading `Bearer ` automatically, so it won't double up in the auth header.

## Environment Variables

| Variable             | Default                   | Description                                                                                                   |
|----------------------|---------------------------|---------------------------------------------------------------------------------------------------------------|
| `OBSIDIAN_API_KEY`   | — (required)              | API key from the plugin's settings. Paste the bare key or the whole `Bearer …` line (the `Bearer ` is stripped). |
| `OBSIDIAN_HOST`      | `https://127.0.0.1:27124` | Base URL of the server. Use `http://127.0.0.1:27123` if you enabled the non-encrypted port instead.           |
| `OBSIDIAN_VERIFY_TLS`| `false`                   | Verify the server's TLS cert. The plugin ships a **self-signed** cert, so `false` is required for the HTTPS port on localhost. Set `true` only if the cert is trusted or you use the plain-HTTP port. |

### Why `OBSIDIAN_VERIFY_TLS=false`?

The plugin's HTTPS port serves a self-signed certificate. Node.js rejects that by
default (`curl` without `-k` fails with error 60). Since the connection is to
**loopback (127.0.0.1)**, there's no meaningful MITM risk, so the wrapper disables
Node TLS verification for its own process. If you'd rather keep verification on,
export `NODE_EXTRA_CA_CERTS` pointing at the plugin's CA cert (downloadable from
its settings) and set `OBSIDIAN_VERIFY_TLS=true`.

## Usage

```bash
atk mcp show obsidian-local-rest-api      # inspect the resolved MCP config
atk setup obsidian-local-rest-api         # change the API key / host / TLS later
```

After `atk plug obsidian-local-rest-api --claude`, the tools below become
available to the agent.

## MCP Tools

Verified against the live server (`tools/list`) — 16 tools:

| Tool                     | Description                                                                  |
|--------------------------|------------------------------------------------------------------------------|
| `vault_list`             | List files and subdirectories inside a vault directory.                      |
| `vault_read`             | Read a vault file's content and metadata.                                    |
| `vault_write`            | Create or overwrite a vault file with the given content.                     |
| `vault_append`           | Append content to the end of a vault file (creates it if missing).           |
| `vault_patch`            | Patch a section of a file by heading, block reference, or frontmatter field. |
| `vault_delete`           | Delete a file from the vault.                                                |
| `vault_move`             | Move (rename) a vault file to a new path.                                    |
| `vault_get_document_map` | Return a file's structure: heading paths, block refs, frontmatter keys.      |
| `active_file_get_path`   | Return the vault-relative path of the file currently open in Obsidian.       |
| `periodic_note_get_path` | Return the path of the current periodic note (daily, weekly, …).             |
| `search_query`           | Search vault files using a JsonLogic query over each note's metadata.        |
| `search_simple`          | Search vault files using Obsidian's built-in simple text search.             |
| `tag_list`               | Return all tags used across the vault, with usage counts.                    |
| `command_list`           | Return all registered Obsidian commands (`id` + human-readable `name`).      |
| `command_execute`        | Execute an Obsidian command by its ID.                                       |
| `open_file`              | Open (or create) a file in the Obsidian UI.                                  |

It also exposes one MCP **resource**: `openapi-spec` (`obsidian://local-rest-api/openapi.yaml`).

> Several tools (`vault_write`, `vault_append`, `vault_patch`, `vault_delete`,
> `vault_move`, `command_execute`, `open_file`) **mutate your vault or Obsidian
> UI**. Use them deliberately.

## Links

- [Upstream repository](https://github.com/coddingtonbear/obsidian-local-rest-api)
- [Upstream docs](https://coddingtonbear.github.io/obsidian-local-rest-api/)
- [`mcp-remote`](https://www.npmjs.com/package/mcp-remote)
