# Serena — Skill

Serena is an LSP-backed semantic code-intelligence MCP. It gives you the operations a
language server offers — symbol lookup, real reference graphs, atomic refactors, post-edit
diagnostics — instead of text search and hand-edits.

## Prefer Serena tools over the built-in file/search/edit tools when working with code

| If you're about to... | Use this instead |
|---|---|
| `grep -r "fooFn"` to find usages | `find_referencing_symbols` |
| Read several files to learn what a class/function contains | `get_symbols_overview` then `find_symbol` |
| Hand-edit a function body with a string-replace edit | `replace_symbol_body` |
| Search-and-replace a name across many files | `rename_symbol` |
| Grep for an interface to find who implements it | `find_referencing_symbols` on the interface symbol |
| Open a file just to insert one method | `insert_after_symbol` / `insert_before_symbol` |
| Eyeball whether your edit type-checks | check Serena's diagnostics |

Symbol-level question → Serena. Plain literals, logs, config text → built-in search.

## Caveats

- **Language server has to start first.** First call into a fresh project pays a one-time
  spin-up cost (seconds) while the LSP server initialises. Subsequent calls are fast.
- **Project activation.** Serena binds to a project on launch (`--project-from-cwd`). If
  you started your client from the wrong directory, tools will operate on the wrong tree —
  restart the MCP server from the right cwd.
- **Refactoring tools mutate files directly.** They are atomic but irreversible without a
  VCS. Make sure the working tree is clean (or committed) before invoking `rename_symbol`,
  `move_symbol`, `inline_symbol`, or `safe_delete`.

## Stakes

When you grep-and-Edit instead of using the LSP, you miss references the type system would
have caught, leave the user to type-check your guesses, and waste context on file-by-file
archaeology. Serena exists so symbol-level work is one call, not twenty.
