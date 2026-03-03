---
name: ralph-wiggum
description: >
  Orchestrates parallel ATK registry plugin development using a developer/tester
  ping-pong loop. Developer agents build; independent tester agents break. Both run
  autonomously via auggie. Coordinated through ralph-tasks.yaml.
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
| `skipped`           | human           | Intentionally excluded from this batch         |

**`developing` vs `pending`**: `developing` is set the instant ralph.py claims a task.
The agent then does all its work. Only when the **agent itself** writes `ready_for_testing`
into the YAML does the task leave the developer's ownership. If the agent crashes
mid-session, ralph.py can detect the stale state via `--stale-timeout` and reclaim it.

---

## YAML Task File: `ralph-tasks.yaml`

Place at the root of `atk-registry/`.

```yaml
schema_version: "2.0"
project: my-plugin-batch
description: Build a set of ATK registry plugins

process:
  developer_agent: auggie
  developer_flags:
    - "--print"
    - "--model"
    - "sonnet4.6"
    - "--rules"
    - "/path/to/ai-assistant/AGENTS.md"
    - "--workspace-root"
    - "/path/to/atk-registry"
    - "--permission"
    - "bash:allow"
    - "--dont-save-session"
  tester_agent: auggie
  tester_flags:                         # can differ from developer_flags
    - "--print"
    - "--model"
    - "sonnet4.6"
    - "--rules"
    - "/path/to/ai-assistant/AGENTS.md"
    - "--workspace-root"
    - "/path/to/atk-registry"
    - "--permission"
    - "bash:allow"
    - "--dont-save-session"
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

---

## Auggie Command for Autonomous Operation

```bash
auggie \
  --print \
  --model sonnet4.6 \
  --rules /Users/oleksandrantoshchenko/ws/public/ai-engineer-toolset/ai-assistant/AGENTS.md \
  --workspace-root /path/to/atk-registry \
  --permission "bash:allow" \
  --dont-save-session \
  --instruction-file /tmp/ralph-prompt-<task-id>.md
```

Key flags for non-interactive operation:
- `--print`: one-shot mode — no interactive prompts, exits when done
- `--model sonnet4.6`: Claude Sonnet 4.6 via Augment
- `--rules`: your engineering standards injected into every session
- `--workspace-root`: the repo auggie will index and operate on
- `--permission "bash:allow"`: approve shell commands without pausing to ask
- `--dont-save-session`: keeps session history clean across many parallel agents
- `--instruction-file`: ralph.py writes the prompt to a temp file and passes it here

**Running ralph.py (developer + tester in parallel):**

```bash
# Developer workers — each claims 'pending' tasks and builds
python skills/ralph-wiggum/ralph.py \
  --role developer --tasks ralph-tasks.yaml --worker-id dev-a &
python skills/ralph-wiggum/ralph.py \
  --role developer --tasks ralph-tasks.yaml --worker-id dev-b &

# Tester workers — each claims 'ready_for_testing' tasks and breaks things
python skills/ralph-wiggum/ralph.py \
  --role tester --tasks ralph-tasks.yaml --worker-id test-a &
python skills/ralph-wiggum/ralph.py \
  --role tester --tasks ralph-tasks.yaml --worker-id test-b &
```



---

## Developer Agent — What You Must Do

You are the DEVELOPER. Your job is to build one ATK registry plugin and hand it to
an independent tester. Read the `create-atk-plugin` SKILL.md carefully — it defines
every requirement. Then implement, self-test, commit, and update the task file.

**Steps (in order):**

1. Read `create-atk-plugin/SKILL.md` in full before writing a single file.
2. If there are open bugs in `bugs[]`, read each one carefully. You will address them.
3. Create `plugins/<name>/` with `plugin.yaml` and all files required by the SKILL.
4. Full implementations only — no stub scripts, no `echo "TODO"`, no placeholder configs.
5. Run `make validate` from the repo root. Fix every error. Repeat until it passes.
6. Self-test the lifecycle: `atk add ./plugins/<name>` → status → stop → start → mcp → remove.
7. If there were open bugs: address each one, then set `status: addressed` on each.
8. Commit: `git add plugins/<name>/ && git commit -m "feat: add <name> plugin (cycle N)"`
9. Update `ralph-tasks.yaml` for this task:
   - `status: ready_for_testing`
   - Increment `dev_cycles`
   - Write your mandatory suggestions (see format below)

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
   - `atk mcp <name>` — is the JSON correct?
   - `atk uninstall <name> --force` then `atk install <name>` — is it idempotent?
   - `atk remove <name> --force` — is cleanup complete?
4. For each previously logged bug: explicitly test whether it is fixed. Note the result.
5. Update `ralph-tasks.yaml` for this task:
   - If **all tests pass**: set `status: complete`, `completed_at: <now>`
   - If **any bugs found**: set `status: pending` (sends back to developer)
   - Write each bug as a structured entry in `bugs[]`
   - Write your mandatory suggestions

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

**Suggestion YAML format:**
```yaml
suggestions:
  - id: "s001"
    cycle: 1
    author_role: developer              # or: tester
    type: skill_bug                     # skill_bug | atk_bug | process_improvement | implementation_note
    status: open
    description: |
      The SKILL.md says to use 'docker compose up -d' in the start lifecycle, but
      on macOS Sequoia (Docker Desktop 4.x) this fails silently when the compose
      file uses the 'platform: linux/amd64' key without a matching buildx context.
      The SKILL does not mention this restriction at all.
    proposed_fix: |
      Add a note to the "start" lifecycle section of create-atk-plugin/SKILL.md:
      "If using platform: linux/amd64, ensure Docker Desktop has Rosetta enabled
      (Settings → General → Use Rosetta). Without it, 'docker compose up' exits 0
      but no container starts."
```

The human running ralph reviews suggestions between batches and updates
`create-atk-plugin/SKILL.md` accordingly. Over iterations, the SKILL gets sharper,
agents make fewer mistakes, and cycles get shorter.

---

## Merging Completed Plugins

After `status: complete`, each plugin lives on branch `plugin/<name>`:

```bash
# Review before merging
git checkout plugin/my-plugin
make validate
atk add ./plugins/my-plugin   # one final lifecycle test

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
