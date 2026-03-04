---
name: ralph-wiggum
description: >
  Skill for driving the Ralph Wiggum parallel plugin factory: create task files,
  run developer/tester ping-pong loops, monitor progress, and merge results. Use
  when asked to build ATK plugins via Ralph, create a task file, or run/monitor
  the ralph.py orchestrator.
---

# Ralph Wiggum — Developer/Tester Ping-Pong Loop

The Ralph Wiggum technique (Geoffrey Huntley): AI coding agents run in a tight loop,
one task per iteration, fresh context each time, a living task file as backlog.

Applied here with **two specialized roles** to eliminate confirmation bias:
- **Developer**: builds the plugin, self-validates, hands off to testing
- **Tester**: independently breaks the plugin, logs bugs, hands back to developer

A developer who tests their own work wants to *prove* it works.
A separate tester wants to *find* what doesn't. Same code, opposite mindsets.

---

## Project Context

**`atk-registry`** is a Git repository containing ATK (AI Toolkit) plugin definitions.
ATK is a CLI (`uv tool install atk-cli`) that lets developers install, configure, and
manage AI development tools (MCP servers, databases, observability stacks) through a
declarative YAML manifest at `~/.atk/manifest.yaml`.

**Repository layout:**

```
atk-registry/
  plugins/              ← one directory per completed plugin
    <name>/
      plugin.yaml       ← machine-readable spec (required)
      README.md         ← human-readable guide (required)
      SKILL.md          ← agent guide for using the plugin (optional)
      install.sh / start.sh / stop.sh / uninstall.sh  ← lifecycle scripts (if needed)
  skills/
    ralph-wiggum/
      ralph.py          ← the loop orchestrator (this skill's engine)
      SKILL.md          ← this file
    create-atk-plugin/
      SKILL.md          ← authoritative guide for building any ATK plugin
  Makefile              ← `make validate` validates all plugins
  index.yaml            ← registry index (auto-generated, do not edit)
```

The **authoritative plugin spec** is `skills/create-atk-plugin/SKILL.md`. Developer
agents receive it in full. Tester agents receive only its Testing Protocol section
(so they probe the plugin against the spec, not the implementation).

**Task files** (`ralph-tasks.yaml`, `ralph-batch-2.yaml`, etc.) live at the registry
root and are **gitignored** (`ralph-*.yaml`, `ralph-*.lock`) — operator artefacts,
not source. Split large batches into multiple files (10–15 tasks each).

---

## The Ping-Pong Loop

```
                 ┌─────────────────────────────────────────────┐
  Multiple       │  Developer Agent (ralph.py --role developer) │
  devs pick ────►│  1. claim pending task                       │
  tasks in       │  2. read create-atk-plugin SKILL.md         │
  parallel       │  3. implement plugin, self-test lifecycle    │
                 │  4. run make validate                        │
                 │  5. commit; mark: ready_for_testing          │
                 │  6. write MANDATORY suggestions              │
                 └──────────────────────┬──────────────────────┘
                                        │  status: ready_for_testing
                 ┌──────────────────────▼──────────────────────┐
  Multiple       │  Tester Agent (ralph.py --role tester)       │
  testers pick ─►│  1. claim ready_for_testing task             │
  tasks in       │  2. read task spec only — NOT the SKILL.md  │
  parallel       │  3. run full ATK lifecycle: add→test→remove  │
                 │  4. log ALL bugs found (structured)          │
                 │  5. mark: complete OR back to pending        │
                 │  6. write MANDATORY suggestions              │
                 └──────────────────────┬──────────────────────┘
                          bugs found?   │   no bugs?
                 ┌────────────────────  │
                 │ status: pending      │   status: complete
                 │ (with bug list)      │
                 ▼                      ▼
           Developer picks          Done ✓
           up again, reads
           bug list, fixes
```

---

## Task Status Lifecycle

```
pending ──► developing ──► ready_for_testing ──► testing ──► complete
                                ▲                    │
                                └──── pending ───────┘
                                       (bugs found → back to developer)
```

| Status              | Set by          | Meaning                                        |
|---------------------|-----------------|------------------------------------------------|
| `pending`           | human / tester  | Ready for a developer to claim                 |
| `developing`        | ralph.py (dev)  | A developer is actively building it            |
| `ready_for_testing` | developer agent | Built and self-tested; needs independent QA    |
| `testing`           | ralph.py (test) | A tester is actively running the test suite    |
| `complete`          | tester agent    | All tests passed; plugin is production-ready   |
| `failed`            | ralph.py        | Meta-failure (worktree error, stale lock, etc) |
| `skipped`           | human / ralph.py (max_cycles) | Intentionally excluded, or cycle limit reached |

**`developing` vs `pending`**: `developing` is set the instant ralph.py claims a task.
The agent then does all its work. Only when the **agent itself** writes `ready_for_testing`
into the YAML does the task leave the developer's ownership. If the agent crashes
mid-session, ralph.py can detect the stale state via `--stale-timeout` and reclaim it.

---

## YAML Task File Schema

Place task files at the root of `atk-registry/`. Name them `ralph-*.yaml`
(e.g. `ralph-tasks.yaml`, `ralph-batch-2.yaml`) — the wildcard pattern is gitignored.

```yaml
schema_version: "2.0"
project: my-plugin-batch
description: Build a set of ATK registry plugins

process:
  developer:
    cmd: auggie                         # any CLI command — auggie, claude, custom script
    flags:
      - "--print"
      - "--model"
      - "sonnet4.6"
      - "--rules"
      - "/path/to/ai-assistant/AGENTS.md"
      - "--permission"
      - "bash:allow"
    instruction_flag: "--instruction-file"   # flag for passing the prompt file; null → stdin
    workspace_flag: "--workspace-root"       # flag for passing worktree path; null → skip
  tester:                               # can differ from developer
    cmd: auggie
    flags:
      - "--print"
      - "--model"
      - "sonnet4.6"
      - "--rules"
      - "/path/to/ai-assistant/AGENTS.md"
      - "--permission"
      - "bash:allow"
  worktree_base: /tmp/ralph-worktrees   # base dir for git worktrees
  branch_prefix: "plugin/"              # branch = plugin/<task-name>
  max_cycles: 5                         # max dev→test cycles before escalating

tasks:
  - id: "001"
    name: my-plugin
    description: |
      Create an ATK registry plugin for <tool>.
      [Enough detail for BOTH developer AND tester to understand what the plugin
      should do — this description IS the shared specification.]
    status: pending
    worker_id: null
    branch: null
    dev_cycles: 0                       # incremented each developer pass
    started_at: null
    completed_at: null

    bugs: []
    # Filled by testers. Format:
    #   - id: "b001"
    #     found_in_cycle: 1
    #     severity: critical | major | minor
    #     status: open | addressed | wont_fix
    #     description: |
    #       Expected: X. Actual: Y. Exact commands that revealed it.
    #     steps_to_reproduce: |
    #       atk add ./plugins/my-plugin
    #       atk start my-plugin
    #       curl http://localhost:PORT/health  # returned 503, expected 200
    #     addressed_in_cycle: null

    suggestions: []
    # MANDATORY — every agent, every cycle. Format:
    #   - id: "s001"
    #     cycle: 1
    #     author_role: developer | tester
    #     type: skill_bug | atk_bug | process_improvement | implementation_note
    #     status: open | noted
    #     description: |
    #       Elaborate, specific description of the gap or issue discovered.
    #       Quote the exact text that was confusing or wrong. Be specific.
    #     proposed_fix: |
    #       Which file, which section, what to add/change/remove.
    #       "None" is not an acceptable proposed_fix.
```

**Process config field reference:**

| Field | Default | Description |
|-------|---------|-------------|
| `developer.cmd` | `auggie` | CLI command for the developer role |
| `developer.flags` | `["--print"]` | Flags passed to the developer agent |
| `developer.instruction_flag` | `"--instruction-file"` | Flag to pass the prompt file; `null` → pipe via stdin |
| `developer.workspace_flag` | `"--workspace-root"` | Flag to pass worktree path; `null` → skip (agent uses cwd) |
| `tester.cmd` | `auggie` | CLI command for the tester role |
| `tester.flags` | `["--print"]` | Flags passed to the tester agent |
| `tester.instruction_flag` | `"--instruction-file"` | Same as developer |
| `tester.workspace_flag` | `"--workspace-root"` | Same as developer |
| `worktree_base` | `/tmp/ralph-worktrees` | Base dir where git worktrees are created |
| `branch_prefix` | `plugin/` | Branch name = `{branch_prefix}{task-name}` |
| `max_cycles` | `0` (unlimited) | Auto-skips a task when `dev_cycles` reaches this |

The old flat format (`developer_agent`, `developer_flags`, `tester_agent`, `tester_flags`) is still accepted for backward compatibility but deprecated. New task files should use the nested format above.

---

## Creating a Task File

When asked to create a Ralph task file, generate a YAML file at the registry root:

```bash
# From atk-registry/
cat > ralph-<batch-name>.yaml << 'EOF'
# ... (YAML content below)
EOF
```

**Task description template** — descriptions are the shared specification between
developer and tester. Both roles receive only the task `description`; neither receives
extra context. A good description answers:
- What tool/service is this plugin for? (link to upstream project)
- What type of plugin is it? (MCP-only stdio | MCP-only SSE | service + MCP)
- What is the exact install command or Docker image?
- Which environment variables are required? Which are optional?
- What MCP capabilities must be verified? (name specific tools, not just "GitHub operations")
- Any known gotchas or configuration quirks from the upstream docs?

```yaml
tasks:
  - id: "001"
    name: my-plugin
    description: |
      Create an ATK plugin for <Tool Name> (<upstream-url>).

      Plugin type: <mcp-stdio | mcp-sse | service>
      Install: <exact install command or Docker image>

      Required env vars:
        MY_TOKEN   — API token from https://...
        MY_HOST    — host to connect to (e.g. localhost)

      Optional env vars:
        MY_PORT    — default 8080
        MY_DEBUG   — set "true" to enable verbose logging

      MCP capabilities to verify:
        - tool: create_item — creates a new item; verify it returns item ID
        - tool: list_items  — lists items; verify pagination param works
        - resource: item:///<id> — verify it returns item JSON

      Known gotchas:
        - The server takes ~5 seconds to initialize; health check must retry.
    status: pending
    worker_id: null
    branch: null
    dev_cycles: 0
    started_at: null
    completed_at: null
    bugs: []
    suggestions: []
```

---

## Running the Loop

All commands run from `atk-registry/`. Use `uv run python` (not bare `python`):

**Basic — one developer worker, one tester worker:**
```bash
uv run python skills/ralph-wiggum/ralph.py --role developer --tasks ralph-tasks.yaml &
uv run python skills/ralph-wiggum/ralph.py --role tester    --tasks ralph-tasks.yaml &
```

**Parallel — multiple workers per role (use distinct `--worker-id`):**
```bash
uv run python skills/ralph-wiggum/ralph.py --role developer --tasks ralph-tasks.yaml --worker-id dev-a &
uv run python skills/ralph-wiggum/ralph.py --role developer --tasks ralph-tasks.yaml --worker-id dev-b &
uv run python skills/ralph-wiggum/ralph.py --role tester    --tasks ralph-tasks.yaml --worker-id test-a &
```

**Multiple task files — run workers against each file:**
```bash
uv run python skills/ralph-wiggum/ralph.py --role developer --tasks ralph-tasks.yaml        --worker-id dev-a &
uv run python skills/ralph-wiggum/ralph.py --role developer --tasks ralph-batch-2.yaml      --worker-id dev-b &
```

**One-shot — process exactly one task then exit (useful for debugging):**
```bash
uv run python skills/ralph-wiggum/ralph.py --role developer --tasks ralph-tasks.yaml --once
```

**Recovery — reclaim stale tasks (agent crashed mid-run):**
```bash
uv run python skills/ralph-wiggum/ralph.py --role developer --tasks ralph-tasks.yaml --stale-timeout 3600
```

**All CLI options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--role ROLE` | (required) | `developer` or `tester` |
| `--tasks FILE` | `ralph-tasks.yaml` | Path to task YAML file |
| `--worker-id ID` | `hostname-pid` | Unique worker label; used in worktree dir names |
| `--once` | false | Process exactly one task then exit |
| `--stale-timeout N` | none | Reclaim tasks stuck in `developing`/`testing` for >N seconds |
| `--worktree-base DIR` | from process config | Override worktree base directory |

**How ralph.py works internally (per task):**

1. Acquire exclusive file lock on `{tasks_file}.lock` (via `fcntl.flock`)
2. Scan tasks for the next eligible task (developer → `pending`; tester → `ready_for_testing`)
3. Claim the task: set `status: developing` / `testing`, `worker_id`, `started_at`
4. Create a git worktree on branch `{branch_prefix}{task-name}` in `worktree_base/`
5. Build a role-specific prompt (injecting the full task file path, skill content, and task data)
6. Write the prompt to a temp file; invoke the agent with `--workspace-root <worktree-dir>`
   (ralph.py always overrides `--workspace-root` to the worktree, not the main repo)
7. When the agent exits, remove the worktree; loop to the next task
8. If `max_cycles` is set and `dev_cycles >= max_cycles`, auto-mark the task `skipped`

**Monitoring:**
```bash
# Task status summary
grep "status:" ralph-tasks.yaml | sort | uniq -c

# Open bugs
grep -A3 "severity:" ralph-tasks.yaml | grep -v "^--"

# Active worktrees
git worktree list

# Active branches
git branch | grep plugin/
```

---

## Agent Configuration Reference

ralph.py works with any CLI agent — auggie, claude, a custom shell script, etc. The
`instruction_flag` and `workspace_flag` fields in `AgentConfig` control how the prompt
and worktree path are delivered. Set either to `null` to skip that delivery mechanism.

Key flags for **auggie** (non-interactive operation):

| Flag | Purpose |
|------|---------|
| `--print` | One-shot mode — no interactive prompts, exits when done |
| `--model sonnet4.6` | Claude Sonnet 4.6 via Augment |
| `--rules /path/to/AGENTS.md` | Engineering standards injected into every session |
| `--permission "bash:allow"` | Approve shell commands without pausing to ask |

For agents that read from stdin (e.g. `claude --print`), set `instruction_flag: null`.
For agents that use the subprocess working directory naturally, set `workspace_flag: null`.

---

## Developer Agent — What You Must Do

You are the DEVELOPER. Your job is to build one ATK registry plugin and hand it to
an independent tester. Read the `create-atk-plugin` SKILL.md carefully — it defines
every requirement. Then implement, self-test, commit, and update the task file.

**The task `description` is a starting point, not a ceiling.** If you discover that
the upstream server accepts additional environment variables, supports optional
configuration, or has behaviors the description didn't mention — document them.
Update `plugin.yaml`, the README, and write an `implementation_note` suggestion.
Expanding beyond the spec is correct behaviour, not scope creep.

**Steps (in order):**

1. Read `create-atk-plugin/SKILL.md` in full before writing a single file.
2. If there are open bugs in `bugs[]`, read each one carefully. You will address them.
3. Create `plugins/<name>/` with `plugin.yaml` and all files required by the SKILL.
4. Full implementations only — no stub scripts, no `echo "TODO"`, no placeholder configs.
5. Run `make validate` from the repo root. Fix every error. Repeat until it passes.
6. Self-test the full lifecycle:
   ```bash
   atk add ./plugins/<name>
   atk status
   atk stop <name> && atk start <name>
   atk mcp show <name>      # verify JSON output
   atk uninstall <name> --force && atk install <name>
   atk remove <name> --force
   ```
7. If there were open bugs: address each one, then mark each fixed via the CLI shown in your prompt.
8. Commit: `git add plugins/<name>/ && git commit -m "feat: add <name> plugin (cycle N)"`
9. Mark the task ready for testing via the ralph CLI (command shown in your prompt):
   ```bash
   uv run skills/ralph-wiggum/ralph.py task update \
       --tasks TASKS_FILE --id TASK_ID --status ready_for_testing --dev-cycles N
   ```
   Do NOT edit the tasks YAML directly — the CLI validates the input. (see format below)

**DO NOT** mark `ready_for_testing` until `make validate` passes and the lifecycle test
completes without errors.

---

## Tester Agent — What You Must Do

You are the TESTER. Your job is to find what the developer got wrong — not to confirm
that they got it right. Approach this as a professional QA engineer who is trying to
**break** the plugin, not validate it.

**Critical mindset**: The developer was motivated to make it look working. You are
motivated to find where it actually fails. These are opposite motivations. Lean into
yours. A tester who reports "all tests passed" in the first cycle is being lazy.

**Steps (in order):**

1. Read the task `description` — this is your specification. Do not read the SKILL.md.
   Test the plugin against what it's supposed to do, not against how it was implemented.
2. If there are previously logged bugs, list them out. You will verify each one.
3. Run the full ATK testing protocol (from `create-atk-plugin` SKILL.md, Testing section):
   - `atk add ./plugins/<name>` — does install complete cleanly?
   - `atk status` — does it show running? Are all ports healthy?
   - `atk stop <name>` then `atk start <name>` — does stop/start cycle work?
   - `atk mcp show <name>` — is the JSON correct? Are all expected tools listed?
   - `atk uninstall <name> --force` then `atk install <name>` — is it idempotent?
   - `atk remove <name> --force` — is cleanup complete?
4. For each previously logged bug: explicitly test whether it is fixed. Note the result.
5. Update the task via the ralph CLI (exact commands shown in your prompt):
   - Log each bug: `ralph.py task add-bug --tasks FILE --id ID --severity S --description D --steps S`
   - Mark fixed bugs: `ralph.py task update-bug --tasks FILE --id ID --bug-id BID --status addressed ...`
   - If **all tests pass**: `ralph.py task update --tasks FILE --id ID --status complete`
   - If **any bugs found**: `ralph.py task update --tasks FILE --id ID --status pending`

   Do NOT edit the tasks YAML directly — the CLI validates statuses and rejects invalid values.

**DO NOT** set `status: complete` if any test failed or any previously logged bug
is still reproducible.

---

## Mandatory Suggestions — The Law

Both roles **must** write suggestions every cycle. No exceptions. This is how the
process learns and improves across batches.

**Minimum: 3 suggestions per agent per cycle.** If you can only find 2 things, look
harder. A passing cycle still has process gaps — you just haven't named them yet.

**A suggestion with no `proposed_fix` is incomplete.** If you can describe a problem,
you can propose a fix — even if it is "add a warning note to section X of SKILL.md."

What to write suggestions about:
- Something in `create-atk-plugin/SKILL.md` that was wrong, ambiguous, or missing
- ATK behaviour that differed from what the SKILL or documentation described
- A step in the lifecycle that the SKILL didn't warn you about
- A pattern that tripped you up and would trip up a future agent
- A test that should be required but isn't mentioned anywhere
- A process step in this ralph-wiggum loop that should be improved
- Something you discovered during implementation that the task spec didn't mention

**`implementation_note` suggestions are first-class.** If you found an undocumented
env var, chose a deliberate default, or noticed an upstream quirk that users will hit —
write it up. Do not suppress discoveries just because they weren't explicitly asked for.
These notes are exactly how the task descriptions and SKILL improve across batches.

**Suggestion CLI format** (agents use the CLI — do NOT edit the YAML directly):
```bash
uv run skills/ralph-wiggum/ralph.py task add-suggestion \
    --tasks TASKS_FILE --id TASK_ID \
    --author-role developer \   # or: tester
    --cycle 1 \
    --type skill_bug \          # skill_bug | atk_bug | process_improvement | implementation_note
    --description "The SKILL.md says to use 'docker compose up -d' in the start lifecycle,
but on macOS Sequoia (Docker Desktop 4.x) this fails silently when the compose file uses
'platform: linux/amd64' without a matching buildx context. The SKILL does not mention this." \
    --proposed-fix "Add a note to create-atk-plugin/SKILL.md start section: 'If using
platform: linux/amd64, ensure Rosetta is enabled in Docker Desktop. Without it, compose
exits 0 but no container starts.'"
```

The CLI validates `--type` and rejects the command if `--proposed-fix` is absent.

The human running ralph reviews suggestions between batches and updates
`create-atk-plugin/SKILL.md` accordingly. Over iterations, the SKILL gets sharper,
agents make fewer mistakes, and cycles get shorter.

---

## Merging Completed Plugins

After `status: complete`, each plugin lives on its own branch
(`{branch_prefix}{task-name}`, e.g. `plugin/my-plugin` with the default prefix):

```bash
# Review before merging
git checkout plugin/my-plugin
make validate
atk add ./plugins/my-plugin   # one final lifecycle test
atk mcp show my-plugin        # verify MCP output
atk remove my-plugin --force  # clean up after review

# Merge
git checkout main
git merge plugin/my-plugin --no-ff -m "feat: add my-plugin"
```

---

## Tuning Between Batches

- **Agent used the wrong pattern** → add a "sign" to `create-atk-plugin/SKILL.md`:
  e.g., `"DO NOT use sleep 5 — use retry loops with curl."`
- **Tester found the same bug twice** → developer is not reading bug list carefully.
  Add explicit instruction: `"Before writing any code, read every entry in bugs[] and
  plan how you will address each one."`
- **Suggestions are thin or generic** → add to both role prompts: `"Each suggestion
  must quote the specific text that was wrong or missing. Vague suggestions are not accepted."`
- **Cycle count climbing** → examine suggestions for pattern; fix the root cause in SKILL.md.
- **Agent crashed without updating YAML** → run ralph.py with `--stale-timeout 3600`
  to auto-reclaim tasks stuck in `developing` or `testing` for more than 1 hour.
