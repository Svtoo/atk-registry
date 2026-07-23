# claude-dashboard

A live, visual dashboard for every Claude Code chat. Read the dashboard, not the transcript.

## What it is

Chat output is written for the agent's workflow: long, linear, full of tool
noise. This plugin maintains the same information as structured visual state:
one dashboard per chat, regenerated after every turn, showing what the agent
needs from you, how far the work is, and how it got there. It supplements the
chat, and when it is doing its job it replaces reading the chat entirely.

A small localhost server owns the dashboards. After each turn, a Claude Code
hook triggers a `claude -p` call that updates the chat's dashboard through
typed, schema-validated edit operations; the server folds the delta in, renders,
and serves the result. Everything runs on your machine, bound to 127.0.0.1.

It shows up in two places:

- the Browser pane inside the Claude Code app, opened on the current chat's
  dashboard automatically
- any browser at `http://localhost:7878/`: a landing page of your projects
  (grouped by real git repository, worktrees folded in), a per-project chat
  index, per-chat dashboards, statistics, and settings

## The dashboard, piece by piece

Every section is high-signal by contract: short enough to read in full, and
empty whenever there is nothing worth your attention.

| Section | Answers | What it holds |
|---|---|---|
| Glance (header) | Is this the chat I want, and what's the state? | Title plus a fixed what / where / your-move grid. The 10-second check. |
| Call to action | What must I do right now? | The input the agent is waiting on: asks, decisions, blockers. Items vanish once resolved. Empty is the good state: nothing is blocked on you. |
| To-do | How far are we, and what's left? | The strategic plan and its progress. Defined when the work is scoped, then checked off, so what's left is visible without scrolling. |
| Heads-up | What would I otherwise miss? | Alerts you must see: silent changes, risks the chat buried. Acknowledge a row and it folds away. |
| Journey | How did we get here? | The load-bearing decisions and turning points, one beat each, so the path stays reconstructable in a long chat. |
| Freeform | What reference material matters? | The agent's open canvas: designs, diagrams, key terms, links, anything durable and visual the fixed sections can't hold. |

## Cost and transparency

Every turn triggers a billed `claude -p` call. It runs on your Claude
subscription OAuth (the plugin strips `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN`
so a metered API key is never used). Per-turn cost with the default Sonnet model
is small but not zero; stop it any time with `atk stop claude-dashboard`.

Nothing is hidden: each dashboard's footer states its own regen count, average
tokens in and out, average wall time, total dollar cost, and model. The stats
page aggregates the same across projects and time: volume, cost, latency,
failures and retries.

## Install

Requires Claude Code with an authenticated `claude` CLI, and python3.

```bash
atk add claude-dashboard
atk start claude-dashboard
atk status
```

`atk add` installs the plugin and wires the Claude Code hooks that trigger
dashboard updates; `atk status` shows the server running and healthy.

## Configuration

`atk setup claude-dashboard` prompts for these. The first three can also be
changed live from the Settings page in the UI.

| Variable | Default | Description |
|---|---|---|
| `CCD_MODEL` | `sonnet` | Model alias used for dashboard regeneration |
| `CCD_REGEN_TIMEOUT` | `180` | Seconds before a wedged regeneration is killed |
| `CCD_LOG_LEVEL` | `INFO` | `INFO` or `DEBUG` (DEBUG logs full regen prompts) |
| `CCD_PREVIEW_PANE` | `true` | Auto-open the chat's dashboard in the Browser pane |
| `CLAUDE_PROJECTS_DIR` | `~/.claude/projects` | Where Claude Code keeps chat history |
| `PORT` | `7878` | Server port (set in `.env`; hooks pick it up automatically) |

## Uninstall

```bash
atk remove claude-dashboard
```

This stops the server, unwires the hooks, and deletes the plugin together with
its local database (runtime statistics and regeneration history).

Your Claude Code history is never affected, installed or not: the plugin only
reads transcripts, it never writes them. The generated dashboards under
`~/.claude/projects/` are your data and are left in place.
