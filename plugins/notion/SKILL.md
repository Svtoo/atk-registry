# Notion — Agent Skill

This MCP provides access to the Notion API. Use it to search, read, and write Notion pages and databases — keeping
documentation in sync, querying structured data, and managing page content from chat.

## Tools

### Search & Identity
- **API-post-search**: Search pages and data sources by title across the workspace. Use this first to find page or database IDs when you only know a name.
- **API-get-self**: Retrieve the bot user for the current token — useful to confirm identity and check integration access.
- **API-get-user** / **API-get-users**: Retrieve a specific user or list all workspace users.

### Pages
- **API-retrieve-a-page**: Retrieve a page's metadata and properties (not content — use `API-get-block-children` for content).
- **API-post-page**: Create a new page. Requires a parent `page_id` or `database_id`.
- **API-patch-page**: Update page properties (title, status, tags, etc.). Does not update body content — use block tools for that.
- **API-retrieve-a-page-property**: Read a specific property value from a page (e.g., a date field or status).
- **API-move-page**: Move a page to a different parent location.

### Blocks (Page Content)
- **API-get-block-children**: Read the content of a page or block. Returns a list of content blocks (paragraphs, headings, bullets, etc.).
- **API-patch-block-children**: Append new content blocks to a page or block. Use this to write or extend page content.
- **API-retrieve-a-block**: Read a specific block by ID.
- **API-update-a-block**: Update the text or type of an existing block.
- **API-delete-a-block**: Delete a block from a page.

### Data Sources (Databases)
- **API-query-data-source**: Query a Notion database with filters and sorts. Use `data_source_id` (from `API-retrieve-a-database` or search results).
- **API-retrieve-a-data-source**: Get schema and property definitions for a data source.
- **API-update-a-data-source**: Update data source properties or schema.
- **API-create-a-data-source**: Create a new database inside a page.
- **API-list-data-source-templates**: List available templates in a data source.
- **API-retrieve-a-database**: Retrieve a database and its associated data source IDs.

### Comments
- **API-retrieve-a-comment**: Retrieve comments on a page or block.
- **API-create-a-comment**: Post a comment on a page or block.

## Usage Patterns

**Finding and reading a page:**
1. `API-post-search` with the page title to get the page ID
2. `API-retrieve-a-page` to get metadata and properties
3. `API-get-block-children` to read the page body content

**Updating page content:**
1. `API-post-search` to find the page ID
2. `API-get-block-children` to see current content and block IDs
3. `API-update-a-block` to edit existing blocks, or `API-patch-block-children` to append new content

**Creating a new page:**
1. `API-post-search` to find the parent page ID
2. `API-post-page` with `parent.page_id` and optional content blocks

**Querying a database:**
1. `API-post-search` with `filter: {value: "data_source"}` to find the database
2. `API-retrieve-a-database` to get the `data_source_id`
3. `API-query-data-source` with filters and sorts to retrieve rows

## Notes

- **Content vs. Properties**: Page _properties_ (title, status, dates) are managed with `API-patch-page`. Page _content_ (text, headings, bullets) is managed with block tools (`API-get-block-children`, `API-patch-block-children`, `API-update-a-block`).
- **Integration access**: The integration token must have explicit access to each page or database. If a page isn't returned by search, the integration may not have access — the user must add it via the page's **Connect to integration** menu.
- **Data source vs. database**: v2.0+ uses `data_source_id` for database operations. Use `API-retrieve-a-database` to get the `data_source_id` from a `database_id`.
- **Search scope**: `API-post-search` only returns pages and databases the integration has access to — it does not search all of Notion.

