# OpenMemory (Your Persistent Memory)

OpenMemory is YOUR memory. You own it, maintain it, and rely on it.
It is CRITICAL for you to maintain and develop your memory, it is the only way you can learn the user's preference and
work more effectively!!!

## Core Principle

Think of OpenMemory as your brain's long-term storage across all conversations.
Like human memory, it's imperfect — always confirm assumptions against reality
(codebase-retrieval, tests, actual file contents). When memory contradicts reality,
update the memory.

| Tool               | Purpose                              |
|--------------------|--------------------------------------|
| OpenMemory         | Your model of reality (may be stale) |
| codebase-retrieval | Ground truth for current code state  |
| view               | Ground truth for file contents       |

When OpenMemory says X but reality shows Y → update memory to Y.

## Per-Message Protocol

### On EVERY message from the user:

**Before any other tool call:**

1. BEFORE any other tool call, run OpenMemory queries. No exceptions.
2. List recent memories. If it is a first question in a thread, list 12 recent memories. If it is a follow-up question,
   list 3-5 most recent memories.
3. Query memory for specific information related to the question.
4. Query memory for user's preferences regarding the tasks at hand. If user asks for example to write tests, query for
   user's preferences regarding testing.

If you skip OpenMemory queries, you WILL forget user preferences and repeat past mistakes and disappoint the user. This
is not optional!!!

### On EVERY reply you send:

**Before your final reply:**

1. Store episodic memory, 1-3 sentences on what you did. Always add tag `project-X`, where X is the name of the project
   you are working on.
2. If you learn something new, store it as procedural or semantic memory. If you learned 5 new things store 5
   memories!!!
3. If you confirm something, reinforce it. Otherwise, openmemory will evict it and the user would be disappointed.

If you don't commit, this knowledge dies with the conversation. The next session starts from zero, which will result in
wasted time for the user!

Formats:

- **Episodic**: "Updated auth.py test to cover edge case" — use `metadata: { "sector": "episodic" }`
- **Semantic**: "Library Z requires config flag W in version 2.x"
- **Procedural**: "To deploy project Y: first build, then run make deploy-prod"
- **Reflective**: "I've noticed user prefers explicit over implicit in error handling"

## Mid-Task Querying

Before taking significant actions, query memory for relevant context:

- **Writing tests**: "user's testing preferences", "test patterns in [project]"
- **Making architectural decisions**: "user's preferences for [topic]"
- **Choosing libraries/tools**: "user's preferred tools for [task]"
- **Writing code**: "coding style preferences", "[language] patterns user uses"
- **Debugging**: "known issues with [component]", "past problems in [area]"

Pattern: discover something → query memory for context → act with that context.

## What to Store (Bias Toward Storing)

When in doubt, store it. Categories to actively capture:

| Category            | Examples                                                        |
|---------------------|-----------------------------------------------------------------|
| **Preferences**     | "Prefers explicit assertions with named variables in tests"     |
| **Coding Style**    | "Uses early returns, avoids deep nesting"                       |
| **Tool Choices**    | "Uses uv over pip", "Prefers pytest over unittest"              |
| **Project Context** | "tools repo: MCP infrastructure hub, Docker + poetry"           |
| **Decisions Made**  | "Chose X over Y because Z"                                      |
| **Gotchas/Quirks**  | "Augment sometimes hangs after Say tool — not a tool issue"     |
| **Frustrations**    | "Frustrated by flaky tests" — helps avoid repeating pain points |
| **Work Completed**  | "On 2025-01-08, fixed OpenMemory DELETE 500 error"              |
| **Pending Items**   | "Memory instructions need refinement — revisit after testing"   |

## Memory Sectors

| Sector         | Purpose                                   | Decay               | When to Use                                 |
|----------------|-------------------------------------------|---------------------|---------------------------------------------|
| **episodic**   | Events, work done, time-bound occurrences | Fast (λ=0.015)      | Recording what you did in this session      |
| **semantic**   | Facts, knowledge, timeless truths         | Slow (λ=0.005)      | User preferences, project facts, rules      |
| **procedural** | Skills, how-to, action patterns           | Slow (λ=0.008)      | Commands, workflows, step-by-step processes |
| **emotional**  | Feelings, sentiment                       | Fast (λ=0.020)      | User frustrations, excitement, reactions    |
| **reflective** | Meta-cognition, insights                  | Very slow (λ=0.001) | Patterns you've noticed, lessons learned    |

**CRITICAL: Always specify sector in metadata for episodic memories.**

Automatic classification often misclassifies event descriptions as semantic/procedural. To force the correct sector,
use:

```
metadata: { "sector": "episodic" }
```

This is **required** for all work-completed memories. Without it, events get stored as semantic facts (slow decay)
instead of episodic events (fast decay), polluting your memory with stale work logs.

## Memory Maintenance

You are responsible for memory hygiene:

- **Reinforce** memories that prove useful (boost salience)
- **Update** memories when outdated or incomplete
- **Tag** well for discoverability (project-<name>, topic, etc.)

## Storage Guidelines

- Keep memories atomic and concise (1-4 sentences)
- Store multiple memories for distinct ideas!
- Prefer updating/reinforcing existing memories over duplicating

## What NOT to Store

- Transient debugging details (unless they reveal a pattern)
- Information already in project-specific instructions
- Exact code snippets (store the pattern/decision, not implementation)
