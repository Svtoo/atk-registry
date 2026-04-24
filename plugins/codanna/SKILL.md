# Codanna — Skill

Codanna is a code-intelligence MCP. It answers structural questions about a codebase —
call graphs, blast radius, "where is X called", "find the code that handles Y" — in
milliseconds, without reading every file yourself.

## Prefer codanna over Grep when the question is about code structure

| If you're about to... | Use this instead |
|---|---|
| `grep -r "foo("` to find callers | `find_callers` |
| Read a chain of files to trace what a function does | `get_calls` or `analyze_impact` |
| Guess filenames for "the code that handles X" | `semantic_search_with_context` |
| `grep -r "SomeType"` to find type usages | `analyze_impact` |
| Edit a public function / remove code / change a signature | `analyze_impact` first — mandatory |
| Glob for markdown to find docs on a topic | `search_documents` |

Structure → codanna. Literal strings / logs / config text → Grep.

## Caveats

- Dynamic dispatch has expected false negatives (DI, GraphQL resolvers, event handlers,
  string-loaded modules) — cross-check with Grep in those cases.
- If results look stale (missing fresh code, duplicates from old paths), run `get_index_info`
  and suggest `codanna index --force` to the user.

## Stakes

Agents who default to Grep when codanna would answer burn user context on grep-and-read
archaeology and miss downstream usages `analyze_impact` would have caught. The user installed
this to prevent exactly that. Use it.
