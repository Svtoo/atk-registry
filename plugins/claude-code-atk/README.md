# claude-code-atk

Makes Claude Code follow ATK rules.

## What it does

ATK plugs SKILL.md files into `~/.claude/CLAUDE.md` between `<!-- ATK:BEGIN -->` and `<!-- ATK:END -->` markers via `atk plug --claude`. Claude Code reads CLAUDE.md at session start, but the harness strips the HTML comment markers and inlines the referenced contents — so the model never sees the block boundary and tends to treat the instructions as static documentation rather than a per-turn protocol.

This plugin installs a `UserPromptSubmit` hook that fires before every user message and injects a `<system-reminder>` listing the plugged @-references, telling Claude to:

1. Re-read each SKILL.md.
2. Bootstrap any deferred MCP tools listed there via `ToolSearch`.
3. Execute per-turn actions (memory queries, narration, etc.) before answering.

The hook reads CLAUDE.md from disk on every call, so it always reflects the current set of plugged skills. If no ATK block is present, the hook exits silently.

## Installation

Requires: `python3` (for atomic settings.json merge), Claude Code, and ATK plugged into Claude Code via `atk plug --claude` for at least one skill.

```bash
atk add claude-code-atk
```

Then restart Claude Code.

## What install does

1. Copies `hooks/claude-code-atk-reminder.sh` to `~/.claude/hooks/`.
2. Adds an entry under `hooks.UserPromptSubmit` in `~/.claude/settings.json` invoking the script.
3. Preserves every other setting and hook entry — both reads and writes are scoped to this plugin's exact command string, so other plugins that share the `UserPromptSubmit` event are untouched.

## Uninstall

```bash
atk uninstall claude-code-atk
```

Removes only the script and the settings entry this plugin owns. Empty parent objects are pruned.

## Status

```bash
atk status claude-code-atk
```

Exits 0 if the hook script and settings entry are present, non-zero otherwise.

## Caveats

- **Desktop trust discount**: Claude Code Desktop applies a fixed discount to `UserPromptSubmit` `additionalContext` versus the CLI. The hook still injects the same reminder on Desktop, but agents may still rationalise skipping protocol steps. The CLI honours it reliably.
- **No CLAUDE.md ATK block, no reminder**: If `atk plug --claude` has not been run for any skill, the hook has nothing to reference and exits 0. Plug at least one skill first.

## Links

- [ATK CLI](https://github.com/anthropics/atk)
- Hook protocol: `~/.claude/settings.json` `hooks.UserPromptSubmit`
