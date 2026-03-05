# Slack MCP Plugin for ATK

Slack integration via MCP — list channels, read history, post messages, manage threads, and look up users.

## Overview

This plugin wraps the [zencoderai/slack-mcp-server](https://github.com/zencoderai/slack-mcp-server) npm package,
giving AI agents access to Slack workspaces through the Model Context Protocol. The server uses stdio transport
and is invoked on demand via `npx` — no background service required.

## Installation

Requires: Node.js (for `npx`)

```bash
atk add slack
```

You will be prompted for your `SLACK_BOT_TOKEN` and `SLACK_TEAM_ID`.

### Creating a Slack Bot

1. Visit [https://api.slack.com/apps](https://api.slack.com/apps) and click **Create New App → From scratch**.
2. Under **OAuth & Permissions**, add these Bot Token Scopes:
   - `channels:history` — read messages in public channels
   - `channels:read` — list channels
   - `chat:write` — post messages
   - `reactions:write` — add emoji reactions
   - `users:read` — list workspace users
   - `users.profile:read` — read detailed user profiles
3. Click **Install to Workspace** and copy the **Bot User OAuth Token** (`xoxb-…`).
4. Find your Team ID: open Slack in a browser; the URL path segment starting with `T` is your Team ID.
5. Invite the bot to any channels it needs to read: `/invite @your-bot-name`

## Environment Variables

| Variable            | Default | Description                                                                                |
|---------------------|---------|--------------------------------------------------------------------------------------------|
| `SLACK_BOT_TOKEN`   | —       | **Required.** Bot OAuth token (`xoxb-…`) with the scopes listed above.                    |
| `SLACK_TEAM_ID`     | —       | **Required.** Workspace/team identifier starting with `T` (e.g. `T01ABC123`).             |
| `SLACK_CHANNEL_IDS` | —       | Optional. Comma-separated channel IDs to restrict access. Leave unset for all channels.   |

## Usage

After `atk add slack`, get the MCP configuration for your client:

```bash
atk mcp show slack
atk mcp show slack --json
```

The plugin has no background service — `atk start` / `atk stop` are no-ops and expected to warn.

## MCP Tools

Tool list verified against live `tools/list` response from `@zencoderai/slack-mcp-server@0.0.1`.

### Channels

- **`slack_list_channels`** — List public and private channels the bot is a member of (or pre-defined channels).
  Optional: `limit` (default 100, max 200), `cursor` for pagination.

- **`slack_get_channel_history`** — Get recent messages from a channel.
  Required: `channel_id`. Optional: `limit` (default 10).

### Messages

- **`slack_post_message`** — Post a new message to a channel or DM a user.
  Required: `channel_id`, `text`.

- **`slack_reply_to_thread`** — Reply to a message thread.
  Required: `channel_id`, `thread_ts`, `text`.

- **`slack_get_thread_replies`** — Get all replies in a message thread.
  Required: `channel_id`, `thread_ts`.

- **`slack_add_reaction`** — Add an emoji reaction to a message.
  Required: `channel_id`, `timestamp`, `reaction` (emoji name without colons).

### Users

- **`slack_get_users`** — List all workspace users with basic profile info.
  Optional: `cursor`, `limit` (default 100, max 200).

- **`slack_get_user_profile`** — Get detailed profile information for a specific user.
  Required: `user_id`.

## Links

- [Upstream repository](https://github.com/zencoderai/slack-mcp-server)
- [npm package](https://www.npmjs.com/package/@zencoderai/slack-mcp-server)
- [Slack API — App setup](https://api.slack.com/apps)
- [Slack Bot Token Scopes](https://api.slack.com/scopes)

