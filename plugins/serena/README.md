# serena

LSP-backed semantic code intelligence for AI agents over MCP — symbol-aware retrieval,
reference graphs, atomic refactors, and post-edit diagnostics powered by real language
servers (40+ languages).

## Overview

Serena ([oraios/serena](https://github.com/oraios/serena)) speaks the Language Server
Protocol to whichever language server fits your project (TypeScript, Python, Rust, Go,
Java, Kotlin, Swift, C/C++, Ruby, PHP, C#, …). Instead of grep-and-edit, your agent gets
operations like "find every reference to this symbol", "rename it everywhere", and
"replace this function body" as single, type-aware MCP calls.

## Prerequisites

- macOS or Linux
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) on `PATH`
- Python 3.13 (uv will fetch it if missing — see `uv tool install -p 3.13`)
- `~/.local/bin` on the `PATH` of whichever shell your MCP client launches with

## Installation

Step 1 — add the plugin to ATK (installs `serena` binary via uv, runs `serena init`,
prompts for `SERENA_CONTEXT` — press Enter to accept the default of `ide`):

```bash
atk add ./serena-atk-plugin            # local path
# or, once published to a git remote:
# atk add github.com/<org>/serena-atk-plugin
```

Non-interactive form (one empty line for `SERENA_CONTEXT`, then `-y` to skip the
unverified-plugin prompt):

```bash
printf "\n" | atk add ./serena-atk-plugin -y
```

Step 2 — plug it into the coding agents you use. ATK does NOT auto-register MCP
servers; pick the agents explicitly:

```bash
atk plug serena --claude               # Claude Code
atk plug serena --codex                # Codex
atk plug serena --gemini               # Gemini CLI
atk plug serena --auggie               # Augment Code
atk plug serena --opencode             # OpenCode
# Flags compose: atk plug serena --claude --codex
```

`atk plug` registers Serena's MCP server with the chosen agent and injects this
plugin's `SKILL.md` into its instructions. Restart the agent after plugging.

To undo: `atk unplug serena --claude` (same flag surface as `atk plug`).

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SERENA_CONTEXT` | `ide` | Built-in Serena context name (or path to a custom YAML). Picks the tool subset + system prompt at MCP startup. See **`--context`** below for the catalogue and trade-offs. |
| `SERENA_DASHBOARD` | `off` | Serena's local web dashboard. `off` = no dashboard, no port consumed (plugin default; quiet). `headless` = dashboard runs on `127.0.0.1:<auto-port>` but no browser is opened. `open` = dashboard runs AND a browser tab is opened on every MCP startup (Serena's upstream default — noisy because Serena spawns one tab per session and the port auto-increments). |

Serena's other configuration lives in `~/.serena/` (global) and `<project>/.serena/`
(per-project), not env vars.

## Inspecting / changing the launch command

```bash
atk mcp serena            # human-readable
atk mcp serena --json     # JSON, copy-paste into an MCP client config by hand
```

ATK launches the plugin via a thin wrapper at `$ATK_PLUGIN_DIR/mcp.sh` that reads
`SERENA_CONTEXT` from the environment (ATK injects it from `.env`) and execs:

```
serena start-mcp-server --context "$SERENA_CONTEXT" --project-from-cwd
```

`--project-from-cwd` activates whichever directory the MCP client was started in
(searches for `.serena/project.yml` or `.git`, then falls back to CWD). The first
call into a fresh project pays a one-time LSP spin-up cost; subsequent calls are fast.

### `--context` — what it is, what the options are

A context is a YAML file at
`<serena-install>/serena/resources/config/contexts/<name>.yml` that bundles three
things: (1) a system prompt injected at MCP startup, (2) an `excluded_tools` list
that hides tools from `tools/list`, and (3) a `single_project` flag that locks the
session to one project (and drops `activate_project`).

Built-in contexts that ship with Serena 1.27.0:

| Context | Best for | Excludes | `single_project` | Prompt vibe |
|---|---|---|---|---|
| `ide` *(plugin default)* | Generic CLI coding agents | `read_file`, `create_text_file`, `list_dir`, `find_file`, `execute_shell_command` | true | Mild: "prefer Serena's symbolic tools over reading whole files" |
| `claude-code` | Claude Code specifically | same as `ide` plus `search_for_pattern` | true | **Aggressive.** Tells the agent that `Read` for discovery and `Edit` on code files are FORBIDDEN; written to counteract Claude Code's bias toward its built-ins |
| `codex` | Codex CLI | same as `ide` plus `replace_content` | false | Mild; assumes Codex handles patches itself |
| `vscode`, `copilot-cli`, `jb-copilot-plugin`, `jb-ai-assistant`, `junie`, `antigravity` | IDE-specific assistants | varies | varies | Tailored prompts per IDE |
| `chatgpt`, `agent`, `oaicompat-agent` | Web/desktop chat agents | minimal | false | Full toolset, chat-app framing |
| `desktop-app` | Claude Desktop, OpenWebUI | none | false | "you're chatting in a separate window from the code" — exposes the full file-IO surface |

Why `ide` is the default here: the plugin is agent-agnostic, and `ide` is the most
portable "I'm a CLI coding agent, please give me semantic tools but don't shout at
me" context. It hides the file/list/shell tools that every CLI agent already has,
keeps the symbolic + refactoring tools, and stays out of the agent's way.

**Implications of the choice:**

- *Tool surface depends on context.* Switching to `desktop-app` adds `read_file`,
  `list_dir`, `create_text_file`, `execute_shell_command` — useful in a chat UI,
  redundant noise in a CLI agent.
- *`single_project: true` (in `ide`, `claude-code`) drops `activate_project`* —
  one project per MCP server lifetime. Restart the server (or the client) to switch
  projects. The non-single-project contexts keep `activate_project` so you can
  switch on the fly.
- *Prompts can be coercive.* `claude-code` actively browbeats the agent into using
  Serena; `ide` gently suggests. If you find your agent ignoring Serena in favour
  of its built-ins, switching to `claude-code` is the canonical fix — at the cost
  of a more opinionated prompt.

### Changing the context after install

Three ways, pick whichever fits:

1. **Re-run setup** (interactive prompt):
   ```bash
   atk setup serena
   ```
2. **Edit `.env` directly:**
   ```bash
   echo 'SERENA_CONTEXT=claude-code' >> ~/.atk/plugins/serena/.env
   ```
3. **One-shot env override** (per-launch, useful for experimentation — does not
   persist across MCP client restarts because the client re-reads `.env`).

After any change, re-run `atk plug serena --<agent>` so the agent picks up the new
launch line, and restart the agent.

### Other Serena launch flags

For anything beyond `--context`, edit `mcp.sh` in the plugin directory (or fork
the plugin). The full flag surface from `serena start-mcp-server --help`:

- `--mode <name>` — override the default `('interactive', 'editing')` modes
- `--language-backend [LSP|JetBrains]` — switch the symbolic backend
- `--log-level [DEBUG|INFO|WARNING|ERROR|CRITICAL]`, `--trace-lsp-communication`
- `--tool-timeout <seconds>`
- `--enable-web-dashboard true` / `--open-web-dashboard false` —
  Serena ships a local web dashboard on `127.0.0.1:8000` by default

## MCP Tools

Tools exposed under `--context ide` (the plugin's default), verified live against
`tools/list` on server version 1.27.0 — 24 tools:

**Navigation & retrieval**

| Tool | Purpose |
|------|---------|
| `get_symbols_overview` | High-level symbol map of a file or directory |
| `find_symbol` | Locate symbols by name path; optionally include body / substructure |
| `find_referencing_symbols` | Find everything that references a symbol (LSP-correct) |
| `find_implementations` | List implementations of an interface / abstract method |
| `find_declaration` | Jump to the declaration of a symbol |
| `search_for_pattern` | Flexible regex search across the project, including non-code files |
| `get_diagnostics_for_file` | LSP diagnostics (errors / warnings) for a file |

**Editing & refactoring**

| Tool | Purpose |
|------|---------|
| `replace_content` | Pattern-based content replacement in a file |
| `replace_symbol_body` | Replace an entire symbol's body atomically |
| `insert_after_symbol` | Insert content after a class/method/function definition |
| `insert_before_symbol` | Insert content before a symbol's definition |
| `rename_symbol` | Cross-codebase rename (LSP-aware) |
| `safe_delete_symbol` | Delete a symbol if it has no references; otherwise return them |

**Project & session state**

| Tool | Purpose |
|------|---------|
| `activate_project` | Activate a project by name or path *(hidden in `single_project` contexts)* |
| `get_current_config` | Print active project, tools, contexts, and modes |
| `check_onboarding_performed` | Check whether project onboarding has run |
| `onboarding` | Run first-time project onboarding (writes `.serena/`) |
| `initial_instructions` | Returns Serena's runtime instructions manual |

**Per-project notes (Serena's own memory store, independent of any agent)**

| Tool | Purpose |
|------|---------|
| `write_memory` / `read_memory` / `list_memories` / `delete_memory` / `rename_memory` / `edit_memory` | CRUD over `.serena/memories/*.md` |

The exact surface depends on `--context` — see the `--context` section above for the
trade-offs. Run `atk mcp serena --json` to see the active launch line, or
[Serena's tools docs](https://oraios.github.io/serena/01-about/035_tools.html) for the
full catalogue.

## Links

- [Upstream repository](https://github.com/oraios/serena)
- [Documentation](https://oraios.github.io/serena/)
- [Tools reference](https://oraios.github.io/serena/01-about/035_tools.html)
- [Language support](https://oraios.github.io/serena/01-about/020_programming-languages.html)
