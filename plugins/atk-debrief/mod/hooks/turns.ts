// The chat's turns as the mod records them from its own events: one turn per message the user sends, the turn's
// messages cut from `$.session.messages()`, kept in three rotating tail files. Pure, as board.ts.

import type { PromptOrigin, SessionMessage } from 'claude-code'

import type { TurnRecord, TurnRow } from './prompt'

/** Whether a prompt is the user's own message, and so opens a turn: typed, from the phone or Slack, or sent as theirs. */
export function isUsersOwn(origin: PromptOrigin | undefined): boolean {
  if (!origin) return false
  if (origin.kind === 'plugin') return origin.asUser === true
  return origin.kind === 'composer' || origin.kind === 'bridge' || origin.kind === 'sdk' || origin.kind === 'slack-ping'
}

// The newest turns the prompt reads; each lives in tail-<turn % TAIL_SLOTS>.json and names its turn inside.
export const TAIL_SLOTS = 3

export const tailPathOf = (dir: string, turn: number) => `${dir}/tail-${turn % TAIL_SLOTS}.json`

// What one text of a tail file may hold; the prompt cuts tool output further when a turn is too long for it.
const MAX_TEXT = 200_000
// A tail file stays well under the 4 MiB of UTF-8 the engine writes and reads back.
const MAX_TAIL_BYTES = 3_000_000
// A turn too large for a tail file keeps each of its texts shorter, step by step, until it fits.
const SHORTEST_TEXT = 200
const SHORTER_TEXTS = [20_000, 2_000, SHORTEST_TEXT]

function cut(text: string, max: number): string {
  if (text.length <= max) return text
  const head = Math.floor((max * 3) / 4)
  return `${text.slice(0, head)}\n[… ${text.length - max} characters cut …]\n${text.slice(text.length - (max - head))}`
}

function inputOf(input: unknown, max: number): unknown {
  if (typeof input === 'string') return cut(input, max)
  if (Array.isArray(input)) return input.map(item => inputOf(item, max))
  if (typeof input === 'object' && input !== null) return Object.fromEntries(Object.entries(input).map(([key, value]) => [key, inputOf(value, max)]))
  return input
}

/** A message as a tail file keeps it: its text, tool calls and tool output, each long text cut to `max`. */
function rowOf(message: SessionMessage, max = MAX_TEXT): TurnRow {
  const row: TurnRow = { role: message.role, text: cut(message.text, max) }
  if (message.toolUses.length > 0) row.toolUses = message.toolUses.map(use => ({ id: use.tool_use_id, name: use.tool, input: inputOf(use.input, max) }))
  if (message.toolResults?.length) row.toolResults = message.toolResults.map(result => ({ id: result.tool_use_id, text: cut(result.text, max) }))
  return row
}

/** A text's size in UTF-8 bytes, as the engine counts a file. */
export function bytesOf(text: string): number {
  let bytes = 0
  for (const char of text) {
    const code = char.codePointAt(0) ?? 0
    bytes += code < 0x80 ? 1 : code < 0x800 ? 2 : code < 0x10000 ? 3 : 4
  }
  return bytes
}

/**
 * The turn as a tail file holds it. A turn too large for one keeps its texts shorter, step by step; a turn of so many
 * messages that the shortest texts do not fit keeps its prompt and its newest messages that do.
 */
export function tailOf(turn: number, messages: SessionMessage[]): TurnRecord {
  for (const max of [MAX_TEXT, ...SHORTER_TEXTS]) {
    const record = { turn, rows: messages.map(message => rowOf(message, max)) }
    if (bytesOf(JSON.stringify(record)) <= MAX_TAIL_BYTES) return record
  }
  const [first, ...rest] = messages.map(message => rowOf(message, SHORTEST_TEXT))
  const kept: TurnRow[] = []
  let bytes = bytesOf(JSON.stringify({ turn, rows: first ? [first] : [] }))
  for (const row of rest.reverse()) {
    const size = bytesOf(JSON.stringify(row)) + 1
    if (bytes + size > MAX_TAIL_BYTES) break
    bytes += size
    kept.unshift(row)
  }
  return { turn, rows: first ? [first, ...kept] : kept }
}

/** The tail file's turn when it holds turn `turn`, else null: a slot from an older turn, or a damaged one. */
export function tailRecordOf(json: string, turn: number): TurnRecord | null {
  try {
    const record = JSON.parse(json) as TurnRecord
    return record.turn === turn && Array.isArray(record.rows) ? record : null
  } catch {
    return null
  }
}

/** The text with each run of whitespace as one space, as two copies of one prompt compare: the text the prompt hook
 * gave and the row the messages hold can differ in the newlines around what the engine puts before it. */
export const squeezed = (text: string) => text.replace(/\s+/g, ' ').trim()

const isPromptRow = (message: SessionMessage, text: string) =>
  message.role === 'user' && !message.toolResults?.length && squeezed(message.text) === squeezed(text)

/**
 * Where each prompt's turn starts in `messages`: the index of the user message holding its text, searched backwards so
 * a prompt sent twice finds its latest copy, each before the one after it; -1 when the message list no longer holds
 * it, as after a compaction.
 */
function promptIndexesOf(messages: SessionMessage[], prompts: string[]): number[] {
  const found: number[] = []
  let before = messages.length
  for (let p = prompts.length - 1; p >= 0; p--) {
    let at = -1
    for (let i = before - 1; i >= 0; i--) {
      if (isPromptRow(messages[i] as SessionMessage, prompts[p] ?? '')) {
        at = i
        break
      }
    }
    found.unshift(at)
    if (at !== -1) before = at
  }
  return found
}

// A turn whose prompt the list lost, with no turn before it to start after, keeps at most these last messages, so a
// compacted chat sends no history.
const LOST_PROMPT_ROWS = 200

const isPlainUserRow = (message: SessionMessage) => message.role === 'user' && !message.toolResults?.length && message.text.trim() !== ''

/**
 * Each prompt's turn as the messages from its prompt to the next one. A turn whose prompt the list does not hold as
 * typed (a slash command shows as its expansion; a compaction drops it) starts with the prompt's own text: the last
 * such turn takes the messages from the first plain user message after `previousStart`, where the turn before it began,
 * else the last few messages; an earlier one takes none.
 */
export function turnsOf(messages: SessionMessage[], prompts: string[], previousStart = -1): SessionMessage[][] {
  const starts = promptIndexesOf(messages, prompts)
  const last = prompts.length - 1
  // The newest prompt, when the messages do not hold it as typed, starts at the first plain user message after the
  // turn before it: the batch's own last prompt found, else the one recorded before the batch.
  let inferred = -1
  if (last >= 0 && starts[last] === -1) {
    const before = starts.slice(0, last).filter(at => at !== -1).at(-1) ?? previousStart
    if (before !== -1) inferred = messages.findIndex((message, at) => at > before && isPlainUserRow(message))
  }
  const startOfTurn = (index: number) => (index === last && inferred !== -1 ? inferred : (starts[index] ?? -1))
  return prompts.map((text, index) => {
    const start = startOfTurn(index)
    const next = prompts.map((_, later) => startOfTurn(later)).slice(index + 1).find(at => at !== -1) ?? messages.length
    const lost: SessionMessage = { role: 'user', text, toolUses: [] }
    if (index === last && inferred !== -1) return [lost, ...messages.slice(inferred)]
    if (start !== -1) return messages.slice(start, next)
    return index === last ? [lost, ...messages.slice(-LOST_PROMPT_ROWS)] : [lost]
  })
}

/** A prompt the user sent, and whether they typed it over a running turn, so the engine held it for a turn of its own. */
export type PendingPrompt = { text: string; isMidTurn: boolean }

/**
 * How many of the pending prompts a turn's end can record: all but the newest typed over the running turn that the
 * messages do not hold yet, since that one still waits for its own turn. Only a copy after the prompt before it counts:
 * "yes" or "continue" may well stand earlier in the chat.
 */
export function recordableOf(messages: SessionMessage[], pending: PendingPrompt[], lastPrompt: string | null = null): number {
  let count = pending.length
  while (count > 0) {
    const newest = pending[count - 1] as PendingPrompt
    if (!newest.isMidTurn) break
    const previous = count > 1 ? (pending[count - 2] as PendingPrompt).text : lastPrompt
    const isSameText = previous !== null && squeezed(previous) === squeezed(newest.text)
    const after = previous === null ? -1 : isSameText ? (promptIndexesOf(messages, [previous, newest.text])[0] ?? -1) : startOf(messages, previous)
    if (startOf(messages, newest.text) > after) break
    count -= 1
  }
  return count
}

/** Where the prompt's latest copy starts in the messages, or -1 when they no longer hold it. */
export const startOf = (messages: SessionMessage[], prompt: string) => promptIndexesOf(messages, [prompt])[0] ?? -1

/** The newest turn again, when a turn ran with no prompt of its own (a task notice): from its prompt to the end. */
export function latestTurnOf(messages: SessionMessage[], prompt: string): SessionMessage[] | null {
  const [start = -1] = promptIndexesOf(messages, [prompt])
  return start === -1 ? null : messages.slice(start)
}

/** What the user typed before the first of `prompts`, less task notices and commands: what a fork brought from the chat it left. */
export function earlierPromptsOf(messages: SessionMessage[], prompts: string[]): string[] {
  const [first = -1] = prompts.length > 0 ? promptIndexesOf(messages, prompts) : [messages.length]
  const end = first === -1 ? messages.length : first
  return messages
    .slice(0, end)
    .filter(m => m.role === 'user' && !m.toolResults?.length && m.text.trim() !== '' && !m.text.trimStart().startsWith('<'))
    .map(m => m.text)
}

/**
 * Where a fork left a chat, from the hashes of the fork's earlier prompts and the chat's own fingerprints, each
 * `turn:hash`: the turn of the last earlier prompt that chat recorded, when every earlier prompt it recorded falls on
 * one of its turns in the same order. A message that opened no turn there (a notice) or one it recorded otherwise (a
 * slash command, as typed rather than expanded) is passed over. Null when they do not line up, or share too little: a
 * fork with two earlier prompts or more must share two, so a lone common prompt ("continue") is no match.
 */
export function forkPointOf(earlier: string[], prompts: string[]): { turn: number; shared: number } | null {
  const turnsOfHash = new Map<string, number[]>()
  for (const entry of prompts) {
    const at = entry.indexOf(':')
    const hash = entry.slice(at + 1)
    turnsOfHash.set(hash, [...(turnsOfHash.get(hash) ?? []), Number(entry.slice(0, at))])
  }
  // From the newest back, each prompt takes the latest turn of its own before the one after it took.
  let bound = Number.POSITIVE_INFINITY
  let forkTurn: number | null = null
  let shared = 0
  for (const hash of [...earlier].reverse()) {
    const turns = turnsOfHash.get(hash)
    if (!turns) continue
    const turn = Math.max(...turns.filter(candidate => candidate < bound))
    if (!Number.isFinite(turn)) return null
    forkTurn ??= turn
    bound = turn
    shared += 1
  }
  // Common prompts ("continue", "yes") repeat across chats, so a fork shares at least two and half of what it holds.
  if (forkTurn === null || shared < 2 || shared * 2 < earlier.length) return null
  return { turn: forkTurn, shared }
}
