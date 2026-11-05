import type {
  DebriefBand,
  DebriefFreeform,
  DebriefFreeformPart,
  DebriefHeadsup,
  DebriefNotice,
  DebriefStatus,
  DebriefTodo,
  DebriefTodoStatus,
} from '../types'
import { SVG_BLOCK } from './answer'
import { type Board, boardOf, isOldFormat, verdictKeyOf } from './board'
import { COLORS } from './colors'
import type { BarShare } from './marks'
import type { StoredState } from './rebuild'

const ENTITIES: Record<string, string> = { amp: '&', lt: '<', gt: '>', quot: '"', '#39': "'", nbsp: ' ' }

/** The inline HTML the dashboard agent may write, as Markdown. */
function markdownOf(html: string): string {
  return html
    .replace(/<a\s[^>]*href="([^"]*)"[^>]*>(.*?)<\/a>/gi, '[$2]($1)')
    .replace(/<\/?(b|strong)>/gi, '**')
    .replace(/<\/?(i|em)>/gi, '*')
    .replace(/<\/?code>/gi, '`')
    .replace(/<br\s*\/?>/gi, ' ')
    .replace(/<[^>]+>/g, '')
    .replace(/&(amp|lt|gt|quot|#39|nbsp);/g, (_, name: string) => ENTITIES[name] ?? '')
}

/** Markdown reduced to the words it shows. */
export function plainOf(markdown: string): string {
  return markdown.replace(/\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/[*`]/g, '')
}

const BAR_ORDER: DebriefTodoStatus[] = ['done', 'active', 'open', 'blocked']

const BAR_CELLS = 10

/** Shares the cells out by largest remainder, so each cell is an equal part of the plan. */
function shareOut(counts: BarShare[], cells: number): BarShare[] {
  const total = counts.reduce((sum, share) => sum + share.count, 0)
  const exact = counts.map(share => ({ ...share, exact: (share.count * cells) / total }))
  const left = cells - exact.reduce((sum, share) => sum + Math.floor(share.exact), 0)
  const topped = new Set(exact.toSorted((a, b) => (b.exact % 1) - (a.exact % 1)).slice(0, left).map(share => share.status))
  return exact.map(share => ({ status: share.status, count: share.count, cells: Math.floor(share.exact) + (topped.has(share.status) ? 1 : 0) }))
}

/** The bar's cells per status, done steps first: one per step, shared out once the plan outgrows the bar. */
export function barOf(todos: DebriefTodo[]): BarShare[] {
  const counts = BAR_ORDER.map(status => {
    const count = todos.filter(todo => todo.status === status).length
    return { status, count, cells: count }
  })
  if (todos.length <= BAR_CELLS) return counts.filter(share => share.cells > 0)
  const shares = shareOut(counts, BAR_CELLS)
  const unfinished = shares.filter(share => share.status !== 'done' && share.count > 0)
  // A plan with a step left never reads as finished.
  if (unfinished.length > 0 && unfinished.every(share => share.cells === 0)) {
    for (const share of shares) if (share.status === 'done') share.cells -= 1
    unfinished.reduce((a, b) => (b.count > a.count ? b : a)).cells = 1
  }
  return shares.filter(share => share.cells > 0)
}

const STEP_ORDER: DebriefTodoStatus[] = ['active', 'open', 'blocked']

/** The step the work is on: the first in progress, else the first open, else the first blocked. */
export function stepOf(todos: DebriefTodo[]): DebriefTodo | undefined {
  for (const status of STEP_ORDER) {
    const step = todos.find(todo => todo.status === status)
    if (step) return step
  }
  return undefined
}

/** A Markdown link, which the desktop opens for http and file addresses too. */
export const markdownLinkOf = (label: string, href: string) => `[${label.replace(/[[\]]/g, '\\$&')}](${href})`

const LINK_ICONS: Record<string, string> = { issue: '🎫', pr: '🔀', branch: '🌿', doc: '📄' }

export const linkIconOf = (kind: string) => LINK_ICONS[kind] ?? '🔗'

const SEVERITY_RANK: Record<DebriefHeadsup['sev'], number> = { risk: 0, flag: 1, note: 2 }

const agoOf = (turns: number) => (turns === 0 ? 'this turn' : `${turns} turn${turns === 1 ? '' : 's'} ago`)

/** Where to check; empty when it is not known. */
export const whereOf = (headsup: DebriefHeadsup) => (headsup.where ? `where: ${headsup.where}` : '')

/** How long before this turn a stamp was; empty when the stamp is unknown or later than this turn (an older turn count). */
export function agoSince(stamp: number | null, turn: number): string {
  return stamp === null || stamp > turn ? '' : agoOf(turn - stamp)
}

/** A card the chat shows now: not dismissed by the user nor by a rebuild. */
export const isLiveCard = (card: DebriefFreeform) => !card.isRetired && !card.isDismissed

/** How long ago a rebuild dismissed the card, else how long ago it last changed; empty when that is not known. */
export function freeformAgeOf(card: DebriefFreeform, turn: number): string {
  if (card.isRetired && card.dismissedTurn !== null) return `dismissed ${agoOf(Math.max(0, turn - card.dismissedTurn))}`
  return card.changedTurn === null ? '' : `updated ${agoOf(Math.max(0, turn - card.changedTurn))}`
}

/** How long ago the step was done, else raised; empty when neither is known. */
export function todoAgeOf(todo: DebriefTodo, turn: number): string {
  const ago = agoSince(todo.doneTurn ?? todo.createdTurn, turn)
  return ago && todo.doneTurn !== null ? `done ${ago}` : ago
}

const sentenceOf = (text: string) => (/[.!?…:;]$/.test(text) ? text : `${text}.`)

/** The text as a Markdown quote, every line of it. */
export const quoteOf = (text: string) => text.split('\n').map(line => `> ${line}`).join('\n')

/** The heads-up as one plain line for the agent. */
export function replyOf(headsup: DebriefHeadsup): string {
  const raised = headsup.raisedTurn === null ? '' : `, raised turn ${headsup.raisedTurn}`
  const where = headsup.where ? ` Where: ${plainOf(headsup.where)}` : ''
  return `Dashboard heads-up (${headsup.sev}${raised}): ${sentenceOf(plainOf(headsup.what))} Why: ${sentenceOf(plainOf(headsup.why))}${where}`
}

/** The problem as one plain line for the agent: what it is, the steps that fix it, the detail. */
export function noticeReplyOf(notice: DebriefNotice): string {
  const steps = notice.steps.map((step, index) => `${index + 1}) ${step.text}${step.command ? ` \`${step.command}\`` : ''}`).join(' ')
  return [
    `Dashboard problem: ${sentenceOf(notice.title)} ${sentenceOf(notice.what)}`,
    steps && `Steps: ${steps}`,
    notice.detail && `Detail: ${notice.detail.replace(/\s+/g, ' ').trim()}`,
  ]
    .filter(Boolean)
    .join(' ')
}

export function firstBuildOf(status: DebriefStatus): DebriefBand {
  return { status, hasDashboard: false, phase: null, turn: 0, lastTurn: null, asks: [], headsups: [], ackedHeadsups: [], todos: [], links: [], freeform: [] }
}

// Light and dark values for the theme colours a card's diagram uses.
const SVG_THEME =
  `<style>svg { --fg:#1f2937; --muted:#6b7280; --border:#9ca3af; --accent:${COLORS.indigo}; --ok:${COLORS.green}; --warn:${COLORS.amber}; --bad:${COLORS.red} }\n` +
  '@media (prefers-color-scheme: dark) { svg { --fg:#e5e7eb; --muted:#9ca3af; --border:#6b7280 } }</style>'

function svgPartOf(svg: string): DebriefFreeformPart {
  const open = svg.match(/^<svg\b[^>]*>/i)?.[0] ?? '<svg>'
  const attr = (name: string) => open.match(new RegExp(`\\s${name}="([^"]*)"`, 'i'))?.[1]
  const box = attr('viewBox')?.trim().split(/[\s,]+/).map(Number) ?? []
  const size = (name: string, index: number) => {
    const value = Number.parseFloat(attr(name) ?? '')
    const fallback = box[index]
    return Number.isFinite(value) ? value : fallback !== undefined && Number.isFinite(fallback) ? fallback : null
  }
  // Drawn as a picture, the document needs its namespace.
  const head = attr('xmlns') ? open : open.replace(/^<svg\b/i, '<svg xmlns="http://www.w3.org/2000/svg"')
  return {
    kind: 'svg',
    source: head + SVG_THEME + svg.slice(open.length),
    alt: attr('aria-label') ?? svg.match(/<title>([^<]*)<\/title>/i)?.[1] ?? 'diagram',
    width: size('width', 2),
    height: size('height', 3),
  }
}

// An older build refuses a Markdown element past 10,000 characters, so long text goes in pieces.
const MARKDOWN_PIECE = 9_500

// The text's blocks: what blank lines outside a code fence separate.
function blocksOf(text: string): string[] {
  const blocks: string[] = []
  let block: string[] = []
  let isInFence = false
  for (const line of text.split('\n')) {
    if (line.trimStart().startsWith('```')) isInFence = !isInFence
    if (line.trim() === '' && !isInFence) {
      if (block.length > 0) blocks.push(block.join('\n'))
      block = []
    } else {
      block.push(line)
    }
  }
  if (block.length > 0) blocks.push(block.join('\n'))
  return blocks
}

// A line longer than `room`, cut between characters, never inside one.
function linePartsOf(line: string, room: number): string[] {
  const chars = Array.from(line)
  if (chars.length <= room) return [line]
  const parts: string[] = []
  for (let at = 0; at < chars.length; at += room) parts.push(chars.slice(at, at + room).join(''))
  return parts
}

// Room kept in a piece for the fence lines a cut adds.
const FENCE_ROOM = 100

// A block longer than a piece, cut between its lines; where a cut falls inside a code block, the piece closes it and
// the next opens it again with its language, so every piece of it draws as code.
function cutBlock(block: string): string[] {
  if (block.length <= MARKDOWN_PIECE) return [block]
  const room = MARKDOWN_PIECE - FENCE_ROOM
  const pieces: string[] = []
  // The line that opened the code block the cut is in, else null.
  let fence: string | null = null
  let current: string[] = []
  let size = 0
  const flush = () => {
    if (current.length === 0) return
    pieces.push(current.join('\n') + (fence ? '\n```' : ''))
    current = fence ? [fence] : []
    size = fence ? fence.length + 1 : 0
  }
  for (const line of block.split('\n')) {
    for (const part of linePartsOf(line, room)) {
      if (size + part.length + 1 > room) flush()
      current.push(part)
      size += part.length + 1
    }
    if (line.trimStart().startsWith('```')) fence = fence ? null : line.trim()
  }
  // A piece that would hold only the reopened fence adds nothing.
  if (current.length > 0 && !(current.length === 1 && current[0] === fence)) pieces.push(current.join('\n'))
  return pieces
}

// The text in pieces of at most MARKDOWN_PIECE characters, cut between blocks; a longer block is cut where it must be.
function piecesOf(text: string): string[] {
  const pieces: string[] = []
  for (const block of blocksOf(text)) {
    for (const part of cutBlock(block)) {
      const last = pieces.at(-1)
      if (last !== undefined && last.length + 2 + part.length <= MARKDOWN_PIECE) pieces[pieces.length - 1] = `${last}\n\n${part}`
      else pieces.push(part)
    }
  }
  return pieces
}

/** A card's title line and its parts: the Markdown between its diagrams, and each diagram. */
function freeformOf(body: string): { title: string; parts: DebriefFreeformPart[] } {
  const [first = '', ...rest] = body.trim().split('\n')
  const heading = first.match(/^#{1,6}\s+(.*)$/)
  const text = heading ? rest.join('\n') : body.trim()
  const parts: DebriefFreeformPart[] = []
  const addMarkdown = (chunk: string) => {
    for (const piece of piecesOf(chunk)) parts.push({ kind: 'markdown', text: piece })
  }
  let at = 0
  for (const match of text.matchAll(SVG_BLOCK)) {
    addMarkdown(text.slice(at, match.index))
    parts.push(svgPartOf(match[0]))
    at = match.index + match[0].length
  }
  addMarkdown(text.slice(at))
  return { title: heading?.[1]?.trim() || 'Untitled card', parts }
}

const oldTitleOf = (body: string) => plainOf(markdownOf(body.match(/<h2[^>]*>(.*?)<\/h2>/i)?.[1] ?? '')) || 'Untitled card'

/** The band from the chat's state.json, already read, once it holds a board. */
export function bandOf(stored: StoredState, status: DebriefStatus): DebriefBand {
  const model = boardOf(stored.model)
  const headsups = model.headsup
  const acks = stored.acks ?? {}
  const verdictOf = (key: string) => stored.verdicts?.[key]?.verdict
  const absoluteTurnOf = (relativeTurn: number) => (relativeTurn ? model.turn_base + relativeTurn : null)
  const headsupOf = (item: Board['headsup'][number]): DebriefHeadsup => ({
    id: item.id,
    sev: item.sev,
    what: markdownOf(item.what),
    why: markdownOf(item.why),
    where: markdownOf(item.where),
    raisedTurn: absoluteTurnOf(item.created_turn),
  })

  return {
    status,
    hasDashboard: true,
    phase: model.phase,
    turn: model.turn_base + model.turn,
    lastTurn: model.last_turn.bullets.length
      ? { bullets: model.last_turn.bullets.map(markdownOf) }
      : null,
    asks: model.cta.map(item => ({
      id: item.id,
      text: markdownOf(item.text),
      age: Math.max(0, model.turn - item.created_turn),
      isDismissed: verdictOf(verdictKeyOf('cta', item.id)) === 'dismissed',
    })),
    headsups: [...headsups]
      .reverse()
      .filter(item => !acks[item.id])
      .sort((a, b) => SEVERITY_RANK[a.sev] - SEVERITY_RANK[b.sev])
      .map(headsupOf),
    ackedHeadsups: headsups
      .filter(item => acks[item.id])
      .sort((a, b) => (acks[a.id]?.ackedAt ?? 0) - (acks[b.id]?.ackedAt ?? 0))
      .map(headsupOf),
    todos: model.todo.map((item): DebriefTodo => {
      const verdict = verdictOf(verdictKeyOf('todo', item.id))
      return {
        id: item.id,
        text: markdownOf(item.text),
        status: verdict === 'done' ? 'done' : item.status,
        createdTurn: absoluteTurnOf(item.created_turn),
        doneTurn: absoluteTurnOf(item.done_turn),
        isChecked: verdict === 'done',
        isDropped: verdict === 'dropped',
      }
    }),
    links: model.links
      .filter(link => link.url)
      .map(link => ({ id: link.id, label: plainOf(markdownOf(link.label)), url: link.url, kind: link.kind })),
    freeform: model.freeform.map((slot): DebriefFreeform => {
      const body = slot.body
      const isOld = isOldFormat(body)
      const { title, parts } = isOld ? { title: oldTitleOf(body), parts: [] } : freeformOf(body)
      return {
        id: slot.id,
        title,
        parts,
        changedTurn: absoluteTurnOf(slot.changed_turn),
        dismissedTurn: absoluteTurnOf(slot.dismissed_turn),
        isDismissed: verdictOf(verdictKeyOf('freeform', slot.id)) === 'dismissed',
        isRetired: slot.dismissed_turn > 0,
        isOldFormat: isOld,
      }
    }),
  }
}
