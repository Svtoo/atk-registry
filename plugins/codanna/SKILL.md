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

- **Stale-index tell:** `find_symbol` points at a generated/ignored file (`*.gen.ts`, `dist/`, etc.),
  OR `find_callers`/`analyze_impact` returns empty when you suspect callers exist. Run
  `get_index_info`; suggest `codanna index --force`.
- **Dynamic dispatch** (NestJS DI, GraphQL resolvers, event handlers, string-loaded modules) has
  expected false negatives even on a fresh index — cross-check with Grep.

## Stakes

Agents who default to Grep when codanna would answer burn user context on grep-and-read
archaeology and miss downstream usages `analyze_impact` would have caught. The user installed
this to prevent exactly that. Use it.
