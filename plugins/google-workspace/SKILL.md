# google-workspace — Skill

Google Workspace MCP: access Gmail, Drive, Calendar, Docs, Sheets, Slides, Forms, Tasks, Contacts, and Chat through natural language. Runs via `uvx workspace-mcp --single-user` (taylorwilsdon).

## Tools

### Gmail
- **search_gmail_messages**: Search emails with Gmail operators (e.g. `from:alice@example.com is:unread subject:invoice`). Returns message IDs and metadata.
- **get_gmail_message_content**: Get full email body and headers by message ID.
- **get_gmail_messages_content_batch**: Batch retrieve multiple messages at once.
- **send_gmail_message**: Send an email with To, Subject, and Body.
- **draft_gmail_message**: Save a draft instead of sending.

### Google Drive
- **search_drive_files**: Search Drive using query syntax (e.g. `name contains 'report' and mimeType='application/pdf'`).
- **get_drive_file_content**: Read file content by ID. Supports Google Docs, Sheets, PDFs, and Office formats.
- **get_drive_file_download_url**: Download a Drive file to disk.
- **create_drive_file**: Create a new file, optionally fetching content from a URL.
- **create_drive_folder**: Create a folder in Drive.
- **import_to_google_doc**: Import a Markdown, DOCX, or HTML file as a Google Doc.

### Google Calendar
- **list_calendars**: List all calendars the user can access.
- **get_events**: Retrieve events from a calendar, optionally filtering by time range or query.
- **manage_event**: Create, update, or delete calendar events (action: `create` / `update` / `delete`).
- **query_freebusy**: Check free/busy times across multiple calendars.

### Google Docs
- **get_doc_content**: Read a Google Doc's full content.
- **get_doc_as_markdown**: Export a Google Doc as clean Markdown.
- **create_doc**: Create a new Doc with optional initial content.
- **insert_doc_elements**: Insert text, images, or tables at specific positions.
- **find_and_replace_doc**: Find and replace text throughout a Doc.

### Google Sheets
- **read_sheet_values**: Read values from a range (e.g. `Sheet1!A1:D10`).
- **modify_sheet_values**: Write values to a range.
- **create_spreadsheet**: Create a new spreadsheet.
- **format_sheet_range**: Apply cell formatting (colors, number formats, text wrapping).
- **create_table_with_data**: Create a table and populate it in one operation.

### Other Services
- **Slides**: `get_presentation`, `create_presentation`, `get_page`
- **Forms**: `get_form`, `create_form`, `list_form_responses`
- **Tasks**: `list_tasks`, `get_task`, `manage_task`
- **Contacts**: `search_contacts`, `get_contact`, `manage_contact`
- **Chat**: `list_spaces`, `get_messages`, `send_message`
- **Apps Script**: `list_script_projects`, `get_script_content`, `run_script_function`
- **Custom Search**: `search_custom` (requires `GOOGLE_PSE_API_KEY` + `GOOGLE_PSE_ENGINE_ID`)

## Usage Patterns

- **Finding emails**: Use `search_gmail_messages` first to find message IDs, then `get_gmail_message_content` to read bodies.
- **Finding Drive files**: Use `search_drive_files` with Drive query syntax, then `get_drive_file_content` to read.
- **Creating calendar events**: Use `manage_event` with `action="create"`, providing `summary`, `start`, `end`, and optionally `attendees`.
- **Reading a spreadsheet**: Use `read_sheet_values` with the spreadsheet ID and A1 notation range.
- **Editing a Doc**: Get content with `get_doc_content`, then use `insert_doc_elements` or `find_and_replace_doc`.

## Notes

- **First-time auth**: On first tool call, the server opens a browser for Google OAuth. Tokens are cached in `~/.google_workspace_mcp/credentials/`.
- **Single-user mode**: This plugin runs in `--single-user` mode, meaning it uses stored credentials for a single Google account.
- **Tool tier**: All tools are loaded by default. To limit to core tools, add `--tool-tier core` to the args.
- **No service to start**: This is MCP-only. `atk start/stop` warnings are expected and harmless.

