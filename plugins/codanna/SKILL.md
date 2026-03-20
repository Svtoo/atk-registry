# Codanna — Skill

Codanna provides structural code intelligence for your codebase via MCP. Use it to navigate large codebases without reading every file — it answers "where is this called?", "what does this call?", and "find logic that does X" in milliseconds.

## Tools

- **semantic_search_with_context**: Best first tool. Natural-language query returns matching symbols with callers, callees, and impact graph. Use for "find the authentication logic" or "where is error handling".
- **semantic_search_docs**: Search code documentation (docstrings, comments) by intent. Lower noise than `semantic_search_with_context` when you only need the docs.
- **search_symbols**: Full-text fuzzy search by symbol name. Use when you know the approximate name. Supports `kind` (Function, Struct, etc.), `lang`, and `module` filters.
- **find_symbol**: Exact-name lookup. Use when you know the exact name.
- **find_callers**: Reverse call graph — what calls a given function. Use for "where is `process_payment` called?".
- **get_calls**: Forward call graph — what a function calls. Use for "what does `handle_request` call?".
- **analyze_impact**: Complete dependency analysis — calls, type usage, and composition. Use before modifying a symbol to understand blast radius.
- **search_documents**: Search indexed markdown/text files (project docs, READMEs). Use for RAG against documentation.
- **get_index_info**: Show what files and symbols are indexed. Use to confirm the index is up to date.

## Usage Patterns

**Recommended workflow:**
1. Start with `semantic_search_with_context` or `search_symbols` to find the relevant symbol.
2. Use the returned `symbol_id` with `find_callers`, `get_calls`, or `analyze_impact` for precise lookups (avoids name ambiguity).
3. Read the actual source files for authoritative content — codanna is a navigation tool, not a replacement for reading code.

**Before modifying a symbol:** Run `analyze_impact` with its `symbol_id`. Review ALL relationships before making changes.

**For documentation search:** Run `search_documents` separately from code search. It queries a different index (markdown/text files).

## Notes

- Codanna is **project-scoped**: the index lives in `.codanna/` in each project root. It must be initialised (`codanna init`) and indexed (`codanna index src`) per project before use.
- The `--watch` flag keeps the server alive and reindexes on file changes. No manual reindex needed during active development.
- First run after `codanna index` downloads ~150 MB embedding model to `~/.codanna/models/`. Subsequent runs are instant.
- `find_callers` and `get_calls` show **call relationships only** (invocations with parentheses). For type dependencies and component rendering (JSX, struct fields), use `analyze_impact`.
- Symbol IDs are stable within a session but may change after reindexing. Always use names as fallback.

