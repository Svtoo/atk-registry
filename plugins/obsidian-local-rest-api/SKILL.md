# Obsidian Local REST API (with MCP) — Skill

This MCP connects to a running Obsidian instance through the **"Local REST API
with MCP"** plugin (`<OBSIDIAN_HOST>/mcp/`). Use it to read, search, and edit the
user's Obsidian vault — their personal notes, daily notes, and knowledge base —
without leaving the agent.

## Tools

- **Reading** — `vault_list` (list a directory), `vault_read` (file content +
  metadata), `vault_get_document_map` (a file's heading/block/frontmatter
  structure), `active_file_get_path` (the note open in the UI),
  `periodic_note_get_path` (today's daily note, etc.).
- **Searching** — `search_simple` (Obsidian's built-in text search; start here),
  `search_query` (JsonLogic over note metadata for precise filters),
  `tag_list` (all vault tags with counts).
- **Writing** *(mutating — be deliberate)* — `vault_write` (create/overwrite),
  `vault_append`, `vault_patch` (surgically edit by heading / block ref /
  frontmatter field), `vault_delete`, `vault_move` (rename/move).
- **Obsidian UI / commands** — `command_list` + `command_execute` (run any
  registered Obsidian command), `open_file` (open or create a note in the UI).

## When to use it

- The user asks about, references, or wants to edit their Obsidian vault / notes /
  daily note / "second brain".
- You need to look something up in or capture something to their personal notes.

## When NOT to use it

- For your own persistent agent memory, prefer the dedicated memory tooling — the
  vault is the user's hand-curated knowledge base, not scratch space.

## Usage patterns & caveats

- **Discover paths before reading.** Use `vault_list` / `search_simple` to find
  the real path, then `vault_read`. Don't guess paths.
- **Read before you write.** Prefer `vault_patch` (targeted) over `vault_write`
  (whole-file overwrite) when editing an existing note, and read the file first.
- **Mutations are real and immediate.** `vault_write/append/patch/delete/move`,
  `command_execute`, and `open_file` change the user's live vault or UI. Confirm
  intent before destructive edits (delete, overwrite, move).
- **One vault.** All tools act on whichever vault the connected Obsidian instance
  has open; the server must be running for any call to succeed.
