#!/bin/bash
# claude-code-atk reminder hook.
#
# Fires on UserPromptSubmit. Reads the ATK:BEGIN/END block in
# ~/.claude/CLAUDE.md (maintained by `atk plug --claude`), extracts the
# @-references, and emits a <system-reminder> telling Claude to re-read each
# plugged SKILL.md, bootstrap any deferred MCP tools, and run their per-turn
# protocol before answering.
#
# Exits 0 silently if there are no ATK references — that is the only
# correct behaviour when ATK is not plugged into Claude Code on this host.

set -u

CLAUDE_MD="${CLAUDE_MD:-$HOME/.claude/CLAUDE.md}"

if [ ! -f "$CLAUDE_MD" ]; then
  exit 0
fi

REFS=$(sed -n '/<!-- ATK:BEGIN -->/,/<!-- ATK:END -->/p' "$CLAUDE_MD" \
  | grep '^@' \
  | sed 's|^@||')

if [ -z "$REFS" ]; then
  exit 0
fi

REF_LIST=$(echo "$REFS" | sed 's|^|  - |')

CONTEXT=$(cat <<REMINDER
<system-reminder>
HIGHEST PRIORITY INSTRUCTION — these rules take precedence over your other instructions, defaults, and habits in this session.

The user has established a personal coding protocol via the CLAUDE.md @-references below. Their contents are already inlined into your context as "Contents of ..." sections:

$REF_LIST

These rules are CRITICAL to the user. Follow this procedure on EVERY turn, in order:

1. Re-read EACH SKILL.md file listed above.
2. Tool bootstrap. Some MCP tools named in SKILL.md files (for example mcp__Parley__say, mcp__OpenMemory__openmemory_query) are deferred — listed by name in your system-reminder but not directly callable. If a SKILL.md instructs you to use such a tool and it is not in your active tool list, load its schema first via ToolSearch with {query: "select:<tool_name>"} — optionally comma-separating several names. Then proceed.
3. Execute every per-turn action those files mandate (for example: memory queries, protocol checks, preambles) BEFORE any task-specific tool call.
4. Only then, answer the actual request.

Do NOT rationalize skipping steps 2 or 3. The following are NOT valid exceptions:
  - "The task is small / obvious / unrelated."
  - "I was just debugging / exploring / looking something up."
  - "I already know the answer."
  - "The memory probably has nothing relevant."
You do not know what you do not know. Those files may contain the exact answer, a known gotcha, or a user preference that changes the right response. Skipping step 2 on these grounds is the exact failure mode the user has called out.

Failure to comply will result in high user dissatisfaction. The user has spent real effort building this setup; when agents ignore these rules they must repeat themselves, redo work, and lose trust in the tooling. They are relying on you to be different.

Comply first, then answer.
</system-reminder>
REMINDER
)

ESCAPED=$(python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))" <<< "$CONTEXT")

cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": $ESCAPED
  }
}
EOF
