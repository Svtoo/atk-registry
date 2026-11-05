// The rebuild prompt: the board as the model reads it, the last turns of the chat, and the task. Pure, as board.ts.

import { OUTPUT_FORMAT } from './answer-format'
import { type Ack, type Board, isOldFormat, splitVerdictKey, type VerdictRecord } from './board'

/** One message of a turn as the mod keeps it: what `$.session.messages()` gives, less the tools' stored records. */
export type TurnRow = {
  role: 'user' | 'assistant'
  text: string
  toolUses?: { id: string; name: string; input: unknown }[]
  toolResults?: { id: string; text: string }[]
}

/** One turn of the chat: its number in the board's frame and its messages, from the user's prompt on. */
export type TurnRecord = { turn: number; rows: TurnRow[] }

// The newest turn goes in full, with its tool calls; the two before it as prose only.
const FULL_TURNS = 1
const LIGHT_TURNS = 2

// What the transcript may weigh, in estimated words, to fit the model's context with room to spare; an oversized
// turn has its tool output cut, never the turn itself.
const MAX_TRANSCRIPT_WORDS = 100_000

// A word is a run of letters and digits or one punctuation mark, so dense tool output is not undercounted.
const WORD = /[\p{L}\p{N}_]+|[^\p{L}\p{N}_\s]/gu
// A longer run counts as several words, as base64 or a hash costs tokens by its length.
const MAX_WORD_CHARS = 5

const weightOf = (run: string) => Math.ceil(run.length / MAX_WORD_CHARS)

export function estimateWords(text: string): number {
  let words = 0
  for (const match of text.matchAll(WORD)) words += weightOf(match[0])
  return words
}

/** A tool's output cut to `maxWords`: its head and tail kept, the middle replaced by a note; 0 keeps it whole. */
export function capToolBody(body: string, maxWords: number): string {
  if (maxWords <= 0) return body
  const matches = [...body.matchAll(WORD)]
  const weights = matches.map(match => weightOf(match[0]))
  const total = weights.reduce((sum, weight) => sum + weight, 0)
  if (total <= maxWords) return body

  const headMax = Math.max(1, Math.floor((maxWords * 3) / 4))
  const tailMax = Math.max(1, maxWords - headMax)
  let headCount = 0
  let keptHead = 0
  for (const weight of weights) {
    if (keptHead + weight > headMax) break
    keptHead += weight
    headCount += 1
  }
  let tailStart = matches.length
  let keptTail = 0
  for (let i = matches.length - 1; i >= headCount; i--) {
    const weight = weights[i] ?? 0
    if (keptTail + weight > tailMax) break
    keptTail += weight
    tailStart = i
  }
  // One run alone outweighs the whole budget: cut it by characters.
  if (headCount === 0 && tailStart === matches.length) return `${body.slice(0, maxWords * MAX_WORD_CHARS)}\n[… truncated …]\n`

  const lastHead = matches[headCount - 1]
  const firstTail = matches[tailStart]
  const headText = lastHead ? body.slice(0, (lastHead.index ?? 0) + lastHead[0].length) : ''
  const tailText = firstTail ? body.slice(firstTail.index ?? 0) : ''
  const elided = total - keptHead - keptTail
  return `${headText}\n[… ${elided} words truncated — see the tool call in the chat for the full output …]\n${tailText}`
}

const countToolResults = (rows: TurnRow[]) => rows.reduce((sum, row) => sum + (row.toolResults?.length ?? 0), 0)

/** A turn's messages for the prompt: in full with its tool calls and their output, else the prose alone. */
function renderRows(rows: TurnRow[], isFull: boolean, toolBodyMax = 0): string {
  const out: string[] = []
  for (const row of rows) {
    const rendered: string[] = []
    if (row.text.trim()) rendered.push(row.text)
    if (isFull) {
      for (const use of row.toolUses ?? []) rendered.push(`<tool_use name='${use.name}' id='${use.id}'>\n${JSON.stringify(use.input ?? {}, null, 2)}\n</tool_use>`)
      for (const result of row.toolResults ?? []) rendered.push(`<tool_result for='${result.id}'>\n${capToolBody(result.text, toolBodyMax)}\n</tool_result>`)
    }
    if (rendered.length === 0) continue
    out.push(`[${row.role.toUpperCase()}]`, ...rendered, '')
  }
  return out.join('\n').trim()
}

// ─── The board as the model reads it ─────────────────────────────────

const agoOf = (now: number, when: number) => (now - when <= 0 ? 'now' : `${now - when}t ago`)

/** `created Xt ago, done/changed Yt ago`; a 0 stamp is unknown and left out. */
function stampsOf(now: number, created: number, changed: number, done = 0): string {
  const parts: string[] = []
  if (created) parts.push(`created ${agoOf(now, created)}`)
  if (done) parts.push(`done ${agoOf(now, done)}`)
  else if (changed && changed !== created) parts.push(`changed ${agoOf(now, changed)}`)
  else if (parts.length === 0) parts.push(agoOf(now, changed))
  return parts.join(', ')
}

/**
 * The board for the model: every heads-up row and every live card in full, so it updates by id instead of adding a
 * near duplicate, and each item's age and last reason, so it sees what moved. Ages count from `now`, the chat's turn;
 * `verdicts` are the user's own calls, listed as facts.
 */
export function digestOf(m: Board, now: number, verdicts: Record<string, VerdictRecord> = {}, acks: Record<string, Ack> = {}): string {
  const lines = [
    `# Dashboard state — as of conversation turn ${m.turn}`,
    `phase: ${m.phase}`,
    `essence (what this chat is about): ${m.essence || '(none yet)'}`,
    m.last_turn.bullets.length ? `last_turn (turn ${m.last_turn.turn}): ${m.last_turn.bullets.join(' | ')}` : 'last_turn: (none)',
    '',
    `## CTA (${m.cta.length}) — blockers/questions for the user; remove on resolve`,
  ]
  for (const c of m.cta) lines.push(`- ${c.id} [${stampsOf(now, c.created_turn, c.changed_turn)}: ${c.reason}] ${c.text}`)

  lines.push('', `## Links (${m.links.length}) — the nav chips; upsert by id, remove what stopped mattering`)
  for (const link of m.links) {
    lines.push(`- ${link.id} kind=${link.kind || '-'} label=${link.label} url=${link.url || '-'}`)
    if (!link.url) lines.push('  ⚠ no url, so the chip is hidden from the user: fill the real url via link.upsert, or link.remove it if none exists')
  }

  lines.push('', `## To-do (${m.todo.length}) — full history; done steps never leave`)
  for (const t of m.todo) lines.push(`- ${t.id} ${t.status} [${stampsOf(now, t.created_turn, t.changed_turn, t.done_turn)}: ${t.reason}] ${t.text}`)

  lines.push('', `## Heads-up (${m.headsup.length}) — FULL list; update rows by id as facts change; never add a duplicate row`)
  for (const h of m.headsup) {
    const ack = acks[h.id]
    const isAcked = ack !== undefined && Object.keys(ack).length > 0
    const acked = isAcked && ack.turn ? ` (acked turn ${ack.turn})` : isAcked ? ' (acked)' : ''
    lines.push(`- ${h.id} ${h.sev} [${stampsOf(now, h.created_turn, h.changed_turn)}: ${h.reason}] what=${h.what} | why=${h.why} | where=${h.where}${acked}`)
  }

  const live = m.freeform.filter(card => !card.dismissed_turn)
  lines.push(
    '',
    `## Freeform (${live.length}) — sticky reference cards, shown in full; re-upsert a card by id ONLY when the design it shows actually changed, and then change the minimum`,
  )
  for (const card of live) {
    lines.push(`- ${card.id} [${agoOf(now, card.changed_turn)}: ${card.reason}]`)
    if (isOldFormat(card.body)) lines.push('  ⚠ this card is in the retired HTML format: re-upsert it now as Markdown, each diagram an <svg> block, keeping what it says')
    lines.push(card.body)
  }

  if (Object.keys(verdicts).length > 0) {
    lines.push(
      '',
      '## User verdicts — AUTHORITATIVE clicks by the user, already applied to the state above; never re-add a dropped/dismissed item and never uncheck a user-done one',
    )
    for (const [key, entry] of Object.entries(verdicts)) {
      const [section, id] = splitVerdictKey(key)
      const turn = Math.trunc(Number(entry.turn) || 0)
      lines.push(`- user ${entry.verdict ?? '?'}${turn ? ` (turn ${turn})` : ''}: "${entry.text || '(text not recorded)'}" (${section} ${id})`)
    }
  }
  lines.push('')
  return lines.join('\n')
}

// ─── The prompt ──────────────────────────────────────────────────────

const taskOf = (turn: number) =>
  `This is conversation turn ${turn}. Emit the delta for everything that changed since the state above, plus repairs: ` +
  "listed items that violate their section's definition, or that newer facts contradict, get consolidated, rewritten, " +
  'or removed. Repair incrementally — a handful of repair ops per turn, worst violation first; the dashboard converges ' +
  'over turns. Omit healthy unchanged items; an empty ops list is valid only when nothing changed and nothing is broken. ' +
  'Never create a duplicate of an item already listed — update it by id.'

/** What follows the same prompt when its answer could not be used: that answer, then why, so the model sends it again, fixed. */
export const retryPromptOf = (answer: string, reason: string) =>
  '\n\n# Your previous output was REJECTED. It is below, then the error. Fix the error and re-emit the FULL corrected output: ' +
  'the <update> block with the op-set JSON, then one <freeform ref="…"> block per freeform.upsert.\n' +
  `<previous_output>\n${answer}\n</previous_output>\nError: ${reason}`

type PromptInput = {
  board: Board
  // The chat's last turns, oldest first; the newest goes in full.
  turns: TurnRecord[]
  turn: number
  systemTemplate: string
  verdicts: Record<string, VerdictRecord>
  acks: Record<string, Ack>
}

export type Prompt = { system: string; user: string; transcriptWords: number; isTruncated: boolean }

export function assemblePrompt(input: PromptInput): Prompt {
  const window = input.turns.slice(-(FULL_TURNS + LIGHT_TURNS))
  const rendered = window.map((record, index) => {
    const isFull = index >= window.length - FULL_TURNS
    return { record, isFull, text: renderRows(record.rows, isFull) }
  })

  // When the full turn overflows what is left after the prose, its tool output is cut to a share of the budget.
  let isTruncated = false
  const lightWords = rendered.filter(r => !r.isFull).reduce((sum, r) => sum + estimateWords(r.text), 0)
  const budget = MAX_TRANSCRIPT_WORDS - lightWords
  const fullRows = rendered.filter(r => r.isFull)
  if (fullRows.length > 0 && fullRows.reduce((sum, r) => sum + estimateWords(r.text), 0) > budget) {
    const perTurn = Math.max(1, Math.floor(budget / fullRows.length))
    for (const r of fullRows) {
      if (estimateWords(r.text) <= perTurn) continue
      isTruncated = true
      r.text = renderRows(r.record.rows, true, Math.max(1, Math.floor(perTurn / Math.max(1, countToolResults(r.record.rows)))))
    }
  }

  const transcript = rendered
    .filter(r => r.text.trim())
    .map(r => `<turn n="${r.record.turn}">\n${r.text}\n</turn>`)
    .join('\n')
  const user =
    `<dashboard_state turn="${input.turn}">\n${digestOf(input.board, input.turn, input.verdicts, input.acks)}\n</dashboard_state>\n\n` +
    '<transcript note="recent conversation; the newest turn in full with tool calls, earlier turns as prose">\n' +
    `${transcript}\n</transcript>\n\n` +
    `<task>\n${taskOf(input.turn)}\n</task>\n`
  return { system: `${input.systemTemplate.trim()}\n\n${OUTPUT_FORMAT}`, user, transcriptWords: estimateWords(transcript), isTruncated }
}
