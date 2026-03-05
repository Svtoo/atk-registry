# google-workspace

Google Workspace integration via MCP — search Gmail, read Drive files, manage Calendar events, edit Docs and Sheets from any AI assistant.

## Overview

This plugin runs the [workspace-mcp](https://github.com/taylorwilsdon/google_workspace_mcp) server by taylorwilsdon. It gives AI assistants full access to Gmail, Google Drive, Calendar, Docs, Sheets, Slides, Forms, Tasks, Contacts, and Chat through MCP tools. The server handles Google OAuth automatically: on first use, your browser opens for authorization and tokens are cached for future sessions.

## Installation

**Prerequisites**: Python 3.10+, `uv`/`uvx` installed.

You also need a Google Cloud project with a Desktop Application OAuth credential. There is no API key
option — this server uses OAuth to access your personal Gmail, Drive, Calendar, etc.

> **Note:** You are creating a *private* app for your own use, not a public one. You do **not** need to
> fill in Terms of Service URLs, Privacy Policy URLs, or go through app verification. Keep the app in
> **Testing** mode and add yourself as a test user. That is sufficient for personal use.

### Creating the OAuth Credential

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → create or select a project
2. **Enable the APIs** you want under **APIs & Services → Enabled APIs & Services → + Enable APIs**:
   Gmail API, Google Drive API, Google Calendar API, Google Docs API, Google Sheets API, etc.
3. Go to **APIs & Services → Google Auth Platform** (or search "Google Auth Platform" in the top bar)
   - If you see "Google Auth Platform not configured yet", click **Get started**
   - **App information**: enter any App name and a User support email → click **Next**
   - **Audience**: select **External** (required for personal Google accounts) → click **Next**
   - **Contact information**: enter your email → click **Next**
   - **Finish**: agree to the Google API Services User Data Policy → click **Continue** → **Create**
   - After creation, click **Audience** in the left sidebar → under **Test users**, click **Add users**
   - Add your own Google account email → **Save**
   - The app stays in **Testing** mode. Do not publish it — that's all you need for personal use.
4. Go to **APIs & Services → Credentials → Create Credentials → OAuth Client ID**
   - Application type: **Desktop app**
   - Give it any name, click **Create**
   - Copy the **Client ID** and **Client Secret**

```bash
atk add google-workspace
```

On first tool call, the server opens your browser for Google authorization. Tokens are stored in
`~/.google_workspace_mcp/credentials/` and refreshed automatically.

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GOOGLE_OAUTH_CLIENT_ID` | Yes | — | OAuth 2.0 client ID (Desktop Application type) |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Yes | — | OAuth 2.0 client secret |
| `OAUTHLIB_INSECURE_TRANSPORT` | No | `1` | Allow HTTP localhost OAuth callbacks |

## Usage

This is an MCP-only plugin (no background service).

```bash
# Show MCP configuration for your AI client
atk mcp show google-workspace

# Show MCP configuration as JSON
atk mcp show google-workspace --json
```

## MCP Tools

The server exposes 100+ tools across all Google Workspace services. Core tools include:

**Gmail**
- `search_gmail_messages` — Search emails using Gmail query syntax (e.g. `is:unread from:boss@example.com`)
- `get_gmail_message_content` — Retrieve full email content by message ID
- `send_gmail_message` — Send an email
- `get_gmail_messages_content_batch` — Batch retrieve multiple messages

**Google Drive**
- `search_drive_files` — Search files with Drive query syntax
- `get_drive_file_content` — Read file content (supports Docs, Sheets, PDFs, Office formats)
- `create_drive_file` — Create a new file in Drive
- `create_drive_folder` — Create a folder

**Google Calendar**
- `list_calendars` — List accessible calendars
- `get_events` — Retrieve events from a calendar with time range filtering
- `manage_event` — Create, update, or delete calendar events

**Google Docs**
- `get_doc_content` — Read a Google Doc's content
- `get_doc_as_markdown` — Export a Doc as Markdown
- `create_doc` — Create a new Google Doc

**Google Sheets**
- `read_sheet_values` — Read values from a spreadsheet range
- `modify_sheet_values` — Write values to a range
- `create_spreadsheet` — Create a new spreadsheet

**Other services**: Slides, Forms, Tasks, Contacts, Chat, Apps Script, Custom Search

## Links

- [Upstream repository](https://github.com/taylorwilsdon/google_workspace_mcp)
- [PyPI: workspace-mcp](https://pypi.org/project/workspace-mcp/)
- [Google Cloud Console](https://console.cloud.google.com/)

