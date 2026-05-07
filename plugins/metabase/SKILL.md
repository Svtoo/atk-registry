# Metabase — Agent Skill

This MCP provides access to a Metabase analytics instance. Use it to explore database schemas, run saved
questions, execute SQL, manage dashboards, and browse collections — all via the Metabase REST API.

## Tools

### Dashboards
- **list_dashboards**: List all dashboards. Use first to discover available analytical content.
- **get_dashboard**: Get dashboard details by ID — cards, layout, and settings.
- **get_dashboard_cards**: List all cards (charts, tables) inside a specific dashboard.
- **get_dashboard_related**: Find content related to a dashboard.
- **get_dashboard_revisions**: Review the change history for a dashboard.
- **create_dashboard**: Create a new dashboard in a collection.

### Cards / Questions
- **list_cards**: List all saved questions/cards. Filter by type (e.g., `models`) or `model_id`.
- **get_card**: Get full metadata and query definition for a specific card by ID.
- **execute_card**: Run a saved card and return current data results. This is the primary way to execute a saved Metabase question — pass the card ID.
- **export_card_result**: Execute a card and export results in a specific format (csv, xlsx, json).
- **get_card_dashboards**: Find which dashboards contain a given card.

### Databases
- **list_databases**: List all connected database sources — use to discover available databases and their IDs.
- **get_database**: Get connection details and schema information for a specific database.
- **execute_query**: Run a raw SQL query against a connected database. Requires `database_id` and `query`.

### Tables
- **list_tables**: List tables (optionally filter by IDs). Use after `list_databases` to explore schema.
- **get_table**: Get table schema, field definitions, and metadata.

### Collections
- **list_collections**: List all Metabase collections (organisation folders).
- **get_collection_items**: List cards and dashboards inside a specific collection.

### Search & Other
- **search_content**: Search across all Metabase content. Start here if you know a name but not an ID.
- **list_users**: List all users and their roles.
- **get_metabase_playground_link**: Generate an interactive playground URL for a SQL query.

## Usage Patterns

**Find and run a saved question by name:**
1. `search_content` with the question name to find its card ID
2. `execute_card` with that card ID to get the results

**Explore a database:**
1. `list_databases` to get available database IDs
2. `list_tables` to discover tables (or `get_database` for schema)
3. `get_table` for field-level details

**Run ad-hoc SQL:**
1. `list_databases` to find the target database ID
2. `execute_query` with `database_id` and your SQL string

**Browse a collection:**
1. `list_collections` to find the collection ID
2. `get_collection_items` to see its contents

## Notes

- **Auth**: The server uses `METABASE_API_KEY` if set, otherwise falls back to `METABASE_USERNAME` + `METABASE_PASSWORD`. API key requires Metabase v0.46+.
- **Tool names**: The live server uses `snake_case` names (e.g., `execute_card`, not `run-question`). The upstream README may list them differently.
- **Tool set is configurable via `METABASE_TOOL_SET`**: defaults to `essential` (21 tools). Set to `all` for 80+ tools (incl. dashboard/card mutations like `update_dashboard`, `create_card`), `read` for read-only, or `write` for write-only. Restart the MCP client after changing.
- **`get_dashboard` can be huge**: rich dashboards inline every card's full SQL/MBQL definition. The LLM Quality Dashboard returned 527 KB / 16K lines (59 cards). Prefer `get_dashboard_cards` for layout, then `get_card` on individual IDs.
- **METABASE_URL**: Must not have a trailing slash — all API calls will 404 if it does.
- **Permissions**: The API key or user must have appropriate Metabase permissions. If a resource isn't returned, check access rights in the Metabase admin panel.

