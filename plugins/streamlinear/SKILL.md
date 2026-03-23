# Streamlinear — Skill

Token-efficient Linear MCP for AI coding agents. Exposes the full Linear API through a single `linear` tool
with action dispatch. Use this instead of the official Linear MCP when token budget matters.

## Tool

**`linear`** — Single tool that dispatches to seven actions via the `action` parameter.

## Actions

- **`search`**: Find Linear issues. With no parameters, returns your assigned open (non-completed) issues.
  Supports filters: `query`, `team`, `assignee`, `state`, `priority`, `limit`.
- **`get`**: Fetch full details for a single issue. Accepts `id` as `ABC-123` identifier, full Linear URL, or UUID.
- **`update`**: Modify an issue. Accepts `id` plus any of: `state` (fuzzy-matched), `priority`, `assignee`.
- **`comment`**: Add a comment. Accepts `id` and `body` (markdown supported).
- **`create`**: Create a new issue. Required: `title` and `team` (team identifier, e.g. `"ENG"`).
  Optional: `description`, `state`, `priority`, `assignee`.
- **`graphql`**: Raw GraphQL passthrough for anything not covered by the above actions.
  Pass the query string as the `graphql` parameter.
- **`help`**: Returns full inline documentation with all parameters and GraphQL examples.

## Usage Patterns

- **Check your work**: `{"action": "search"}` — see what's assigned to you right now
- **Look up an issue**: `{"action": "get", "id": "ENG-123"}` — fetch full issue with comments and metadata
- **Move issue to done**: `{"action": "update", "id": "ENG-123", "state": "done"}` — fuzzy state matching works
- **File a bug**: `{"action": "create", "title": "Bug: X crashes on Y", "team": "ENG"}`
- **Advanced queries**: Use `graphql` action for anything not covered — projects, milestones, labels, etc.
- **When stuck**: `{"action": "help"}` — returns full parameter documentation inline

## Notes

- Teams and workflow states are fetched at startup and embedded in the tool description — you can see valid
  values before making calls
- State matching is fuzzy: partial strings work (`"in prog"` → `"In Progress"`)
- `assignee: "me"` resolves to the authenticated user automatically
- The server exits immediately if `LINEAR_API_TOKEN` is missing — check ATK env config if tools are unavailable
- No version pinning: fetched fresh from `github:obra/streamlinear` on each npx invocation (cached by npm)

