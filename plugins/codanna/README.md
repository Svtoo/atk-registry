# codanna

Semantic code-intelligence for AI assistants — instant call graphs, dependency analysis, and semantic search across your codebase via MCP.

## Overview

Codanna is a Rust-based tool that builds a structural index of your code. It lets AI assistants understand function relationships, trace callers/callees, and search by intent rather than keywords. Supports Rust, Python, JS/TS, Java, Kotlin, Go, PHP, C/C++, C#, Clojure, Lua, Swift, GDScript.

Sub-10ms lookups. 75,000+ symbols/second parsing. Works with Claude, Gemini, Codex, and any MCP-compatible client.

## Prerequisites

- macOS or Linux (Windows support is experimental)
- Internet connection (first run downloads ~150 MB embedding model)

## Installation

```bash
atk add codanna
```

This installs the `codanna` binary system-wide (via Homebrew on macOS, install script on Linux).

## Per-Project Setup

Codanna is **project-scoped** — after installing the binary, run these commands inside each project you want to use it with:

```bash
# 1. Initialise — creates .codanna/settings.toml
codanna init

# 2. Index source code (first run downloads ~150 MB embedding model)
codanna index src

# 3. Optional: index documentation files for RAG
codanna documents add-collection docs ./docs
codanna documents index
```

The `.codanna/` directory lives in your project root. Commit it or add it to `.gitignore` as you prefer.

## Usage

After per-project setup, point your MCP client at this plugin:

```bash
atk mcp show codanna
```

The MCP server starts automatically when your AI assistant connects. The `--watch` flag keeps it running and reindexes on file changes.

**Binary path**: macOS (Homebrew): `/opt/homebrew/bin/codanna` · Linux (install script): `~/.local/bin/codanna`  
Make sure the relevant directory is in your `PATH`.

## MCP Tools

Tool list verified against live `tools/list` response (codanna 0.9.17):

| Tool | Description |
|------|-------------|
| `semantic_search_with_context` | Natural-language query returning matching symbols with full context: docs, callers, callees, impact graph |
| `semantic_search_docs` | Semantic search against code documentation (docstrings, comments) |
| `search_symbols` | Full-text fuzzy search for symbols by name, kind, language, or module |
| `find_symbol` | Find a specific symbol by exact name |
| `find_callers` | Find all functions that call a given function (reverse call graph) |
| `get_calls` | Get all functions that a given function calls (forward call graph) |
| `analyze_impact` | Complete impact analysis: everything that depends on a symbol (calls, type usage, composition) |
| `search_documents` | Search indexed markdown/text files (RAG) |
| `get_index_info` | Show what is currently indexed in the project |

## Links

- [GitHub](https://github.com/bartolli/codanna)
- [Documentation](https://docs.codanna.sh)
- [Installation Guide](https://docs.codanna.sh/installation)
- [MCP Reference](https://docs.codanna.sh/reference/mcp-quick)

