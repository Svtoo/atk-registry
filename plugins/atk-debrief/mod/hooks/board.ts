// The chat's board as state.json keeps it, the change set the rebuild model sends, and how one folds into the other.
// Pure: no `$`, so the rebuild's logic is tested as plain functions.

const PHASES = ['planning', 'building', 'blocked', 'review', 'shipped'] as const
type Phase = (typeof PHASES)[number]

const TODO_STATUSES = ['open', 'active', 'done', 'blocked'] as const
type TodoStatus = (typeof TODO_STATUSES)[number]

// A note is a historic row only: the change set cannot raise one.
type Sev = 'risk' | 'flag' | 'note'

type TodoItem = { id: string; text: string; status: TodoStatus; order: number; created_turn: number; changed_turn: number; done_turn: number; reason: string }
type LinkItem = { id: string; label: string; url: string; kind: string; order: number; changed_turn: number; reason: string }
type CtaItem = { id: string; text: string; order: number; changed_turn: number; created_turn: number; reason: string }
type HeadsupItem = { id: string; sev: Sev; what: string; why: string; where: string; order: number; created_turn: number; changed_turn: number; reason: string }
type FreeformSlot = { id: string; body: string; hash: string; changed_turn: number; dismissed_turn: number; reason: string }

export type Board = {
  phase: Phase
  // What the chat is about, the mission in plain words: the model's own memory of it past the turns it reads.
  essence: string
  // The turn of the last rebuild, counted in this chat's frame; turn_base adds the turns of the chats it continues.
  turn: number
  turn_base: number
  seq: number
  last_turn: { bullets: string[]; turn: number }
  links: LinkItem[]
  cta: CtaItem[]
  todo: TodoItem[]
  headsup: HeadsupItem[]
  freeform: FreeformSlot[]
}

export type VerdictRecord = { verdict: string; at?: number; turn?: number; text?: string }
export type Ack = { ackedAt?: number; turn?: number }

const SHORT = 400
// Past this a card alone nears the rebuild's time limit; the answer drops a longer one with a note.
export const FREEFORM_MAX = 50_000
const MAX_OPS = 40
const MAX_VERDICTS = 50

type Json = Record<string, unknown>

const isObject = (value: unknown): value is Json => typeof value === 'object' && value !== null && !Array.isArray(value)
const str = (value: unknown, fallback = '') => (typeof value === 'string' ? value : fallback)
const int = (value: unknown) => (typeof value === 'number' && Number.isFinite(value) ? Math.trunc(value) : 0)
const listOf = (value: unknown): Json[] => (Array.isArray(value) ? value.filter(isObject) : [])
const oneOf = <T extends string>(choices: readonly T[], value: unknown, fallback: T): T =>
  choices.includes(value as T) ? (value as T) : fallback

function emptyBoard(): Board {
  return {
    phase: 'planning',
    essence: '',
    turn: 0,
    turn_base: 0,
    seq: 0,
    last_turn: { bullets: [], turn: 0 },
    links: [],
    cta: [],
    todo: [],
    headsup: [],
    freeform: [],
  }
}

/** The stored board with every field present; a card saved before cards were Markdown loads from `html`. */
export function boardOf(stored: unknown): Board {
  if (!isObject(stored)) return emptyBoard()
  // A board saved before the essence stood on its own kept it in `tldr`.
  const tldr = isObject(stored.tldr) ? stored.tldr : {}
  const last = isObject(stored.last_turn) ? stored.last_turn : {}
  return {
    phase: oneOf(PHASES, stored.phase, 'planning'),
    essence: str(stored.essence, str(tldr.essence)),
    turn: int(stored.turn),
    turn_base: int(stored.turn_base),
    seq: int(stored.seq),
    last_turn: { bullets: Array.isArray(last.bullets) ? last.bullets.filter(b => typeof b === 'string') : [], turn: int(last.turn) },
    links: listOf(stored.links).map(it => ({
      id: str(it.id), label: str(it.label), url: str(it.url), kind: str(it.kind), order: int(it.order), changed_turn: int(it.changed_turn), reason: str(it.reason),
    })),
    cta: listOf(stored.cta).map(it => ({
      id: str(it.id), text: str(it.text), order: int(it.order), changed_turn: int(it.changed_turn), created_turn: int(it.created_turn), reason: str(it.reason),
    })),
    todo: listOf(stored.todo).map(it => ({
      id: str(it.id), text: str(it.text), status: oneOf(TODO_STATUSES, it.status, 'open'), order: int(it.order),
      created_turn: int(it.created_turn), changed_turn: int(it.changed_turn), done_turn: int(it.done_turn), reason: str(it.reason),
    })),
    headsup: listOf(stored.headsup).map(it => ({
      id: str(it.id), sev: oneOf<Sev>(['risk', 'flag', 'note'], it.sev, 'note'), what: str(it.what), why: str(it.why), where: str(it.where),
      order: int(it.order), created_turn: int(it.created_turn), changed_turn: int(it.changed_turn), reason: str(it.reason),
    })),
    freeform: listOf(stored.freeform).map(it => ({
      id: str(it.id), body: str(it.body, str(it.html)), hash: str(it.hash), changed_turn: int(it.changed_turn), dismissed_turn: int(it.dismissed_turn), reason: str(it.reason),
    })),
  }
}

/** A card written before cards were Markdown: one HTML <section>, or no body at all, kept until a rebuild rewrites it. */
export const isOldFormat = (body: string) => !body.trim() || body.trimStart().startsWith('<section')

/**
 * The board as it stood at a turn, as near as the board can tell: without the asks, steps and heads-up raised after
 * it, nor the last turn's bullets when they are of a later turn. What changed later on an older item stays changed.
 */
export function boardAt(board: Board, turn: number): Board {
  if (board.turn <= turn) return board
  const isBefore = (item: { created_turn: number }) => item.created_turn <= turn
  return {
    ...board,
    turn,
    cta: board.cta.filter(isBefore),
    todo: board.todo.filter(isBefore),
    headsup: board.headsup.filter(isBefore),
    last_turn: board.last_turn.turn > turn ? { bullets: [], turn: 0 } : board.last_turn,
  }
}

/** The key a verdict is kept under beside the board: its section, then the item's id. */
export const verdictKeyOf = (section: string, id: string) => `${section}:${id}`

export function splitVerdictKey(key: string): [string, string] {
  const at = key.indexOf(':')
  return at === -1 ? [key, ''] : [key.slice(0, at), key.slice(at + 1)]
}

// ─── The change set ──────────────────────────────────────────────────

type Op =
  | { op: 'todo.upsert'; id?: string; text?: string; status?: TodoStatus; reason: string }
  | { op: 'cta.upsert'; id?: string; text?: string; reason: string }
  | { op: 'cta.remove'; id: string; reason: string }
  | { op: 'link.upsert'; id?: string; label?: string; url?: string; kind?: string; reason: string }
  | { op: 'link.remove'; id: string; reason: string }
  | { op: 'last_turn.set'; bullets: string[] }
  | { op: 'headsup.upsert'; id?: string; sev?: 'risk' | 'flag'; what?: string; why?: string; where?: string; reason: string }
  | { op: 'freeform.upsert'; id?: string; bodyRef: string; reason: string }

export type Update = { phase?: Phase; essence?: string; ops: Op[] }

export class UpdateError extends Error {}

type FieldRule = { kind: 'text'; max?: number } | { kind: 'choice'; choices: readonly string[] } | { kind: 'bullets' }

// Each op's fields; a field absent here is refused, so a misspelt one fails loudly instead of passing as an empty change.
const OP_FIELDS: Record<Op['op'], Record<string, FieldRule>> = {
  'todo.upsert': { id: { kind: 'text' }, text: { kind: 'text', max: SHORT }, status: { kind: 'choice', choices: TODO_STATUSES }, reason: { kind: 'text', max: SHORT } },
  'cta.upsert': { id: { kind: 'text' }, text: { kind: 'text', max: SHORT }, reason: { kind: 'text', max: SHORT } },
  'cta.remove': { id: { kind: 'text' }, reason: { kind: 'text', max: SHORT } },
  'link.upsert': {
    id: { kind: 'text' }, label: { kind: 'text', max: SHORT }, url: { kind: 'text', max: SHORT }, kind: { kind: 'text', max: 40 }, reason: { kind: 'text', max: SHORT },
  },
  'link.remove': { id: { kind: 'text' }, reason: { kind: 'text', max: SHORT } },
  'last_turn.set': { bullets: { kind: 'bullets' } },
  'headsup.upsert': {
    id: { kind: 'text' }, sev: { kind: 'choice', choices: ['risk', 'flag'] }, what: { kind: 'text', max: SHORT }, why: { kind: 'text', max: SHORT },
    where: { kind: 'text', max: SHORT }, reason: { kind: 'text', max: SHORT },
  },
  'freeform.upsert': { id: { kind: 'text' }, bodyRef: { kind: 'text' }, reason: { kind: 'text', max: SHORT } },
}

const REQUIRED: Partial<Record<Op['op'], string[]>> = {
  'cta.remove': ['id'],
  'link.remove': ['id'],
  'last_turn.set': ['bullets'],
  'freeform.upsert': ['bodyRef'],
}

// What a create (no id) must carry.
const CREATE_NEEDS: Partial<Record<Op['op'], string[]>> = {
  'todo.upsert': ['text'],
  'cta.upsert': ['text'],
  'link.upsert': ['label'],
  'headsup.upsert': ['sev', 'what', 'why'],
}

function checkField(where: string, name: string, rule: FieldRule, value: unknown): unknown {
  if (rule.kind === 'bullets') {
    if (!Array.isArray(value) || value.length < 1 || value.length > 3) throw new UpdateError(`${where}.${name}: give 1 to 3 bullets`)
    value.forEach((bullet, index) => {
      if (typeof bullet !== 'string') throw new UpdateError(`${where}.${name}[${index}]: must be a string`)
      if (bullet.length > SHORT) throw new UpdateError(`${where}.${name}[${index}]: at most ${SHORT} characters`)
    })
    return [...value]
  }
  if (typeof value !== 'string') throw new UpdateError(`${where}.${name}: must be a string`)
  if (rule.kind === 'choice' && !rule.choices.includes(value)) throw new UpdateError(`${where}.${name}: must be one of ${rule.choices.join(', ')}`)
  if (rule.kind === 'text' && rule.max !== undefined && value.length > rule.max) throw new UpdateError(`${where}.${name}: at most ${rule.max} characters`)
  return value
}

function opOf(raw: unknown, index: number): Op {
  const where = `ops[${index}]`
  if (!isObject(raw)) throw new UpdateError(`${where}: must be an object`)
  const kind = raw.op as Op['op']
  const fields = OP_FIELDS[kind]
  if (!fields) throw new UpdateError(`${where}.op: must be one of ${Object.keys(OP_FIELDS).join(', ')}`)
  const op: Json = { op: kind }
  for (const [name, value] of Object.entries(raw)) {
    if (name === 'op') continue
    // The schema's own spelling of the field is accepted beside its alias.
    const field = kind === 'freeform.upsert' && name === 'body_ref' ? 'bodyRef' : name
    const rule = fields[field]
    if (!rule) throw new UpdateError(`${where}.${name}: no such field on ${kind}`)
    // An omitted optional field may also come as null.
    if (value === null && field !== 'reason' && !(REQUIRED[kind] ?? []).includes(field)) continue
    op[field] = checkField(where, field, rule, value)
  }
  for (const name of REQUIRED[kind] ?? []) if (op[name] === undefined) throw new UpdateError(`${where}.${name}: required`)
  if (op.id === undefined) {
    for (const name of CREATE_NEEDS[kind] ?? []) {
      if (!op[name]) throw new UpdateError(`${where}: ${kind} without id (create) requires ${CREATE_NEEDS[kind]?.join(', ')}`)
    }
  }
  if ('reason' in fields && op.reason === undefined) op.reason = ''
  return op as Op
}

/** The change set the model sent, checked against its schema; an UpdateError names the first problem. */
export function updateOf(data: unknown): Update {
  if (!isObject(data)) throw new UpdateError('the op-set must be a JSON object')
  const update: Update = { ops: [] }
  for (const [name, value] of Object.entries(data)) {
    if (value === null && name !== 'ops') continue
    if (name === 'phase') update.phase = checkField('', 'phase', { kind: 'choice', choices: PHASES }, value) as Phase
    else if (name === 'essence') update.essence = checkField('', 'essence', { kind: 'text', max: SHORT }, value) as string
    else if (name === 'ops') {
      if (!Array.isArray(value)) throw new UpdateError('ops: must be a list')
      if (value.length > MAX_OPS) throw new UpdateError(`ops: at most ${MAX_OPS} ops`)
      update.ops = value.map(opOf)
    } else throw new UpdateError(`${name}: no such field`)
  }
  return update
}

// ─── Folding it in ───────────────────────────────────────────────────

const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T

/**
 * Folds one rebuild's `update` into a copy of `board`. `turn` is the chat's turn in the board's frame and stamps every
 * item created or changed. An op naming an id the board lacks is skipped, never invented. `hashOf` gives a card body's
 * hash, so an identical body is no change.
 */
export function applyOps(board: Board, update: Update, bodies: Record<string, string>, turn: number, hashOf: (body: string) => string): Board {
  const m = clone(board)
  if (update.phase !== undefined) m.phase = update.phase
  // An empty string clears the essence.
  if (update.essence !== undefined) m.essence = update.essence
  const mint = (prefix: string) => `${prefix}${++m.seq}`

  for (const op of update.ops) {
    if (op.op === 'todo.upsert') {
      if (op.id === undefined) {
        const status = op.status ?? 'open'
        m.todo.push({
          id: mint('t'), text: op.text ?? '', status, order: m.seq, created_turn: turn, changed_turn: turn,
          done_turn: status === 'done' ? turn : 0, reason: op.reason,
        })
        continue
      }
      const it = m.todo.find(item => item.id === op.id)
      if (!it) continue
      if (op.text !== undefined) it.text = op.text
      if (op.status !== undefined) {
        if (op.status === 'done' && it.status !== 'done') it.done_turn = turn
        else if (op.status !== 'done') it.done_turn = 0
        it.status = op.status
      }
      it.changed_turn = turn
      // An omitted reason keeps the stored one.
      if (op.reason) it.reason = op.reason
    } else if (op.op === 'cta.upsert') {
      if (op.id === undefined) {
        m.cta.push({ id: mint('c'), text: op.text ?? '', order: m.seq, changed_turn: turn, created_turn: turn, reason: op.reason })
        continue
      }
      const it = m.cta.find(item => item.id === op.id)
      if (!it) continue
      if (op.text !== undefined) it.text = op.text
      it.changed_turn = turn
      if (op.reason) it.reason = op.reason
    } else if (op.op === 'cta.remove') {
      m.cta = m.cta.filter(item => item.id !== op.id)
    } else if (op.op === 'link.upsert') {
      if (op.id === undefined) {
        m.links.push({ id: mint('l'), label: op.label ?? '', url: op.url ?? '', kind: op.kind ?? '', order: m.seq, changed_turn: turn, reason: op.reason })
        continue
      }
      const it = m.links.find(item => item.id === op.id)
      if (!it) continue
      if (op.label !== undefined) it.label = op.label
      if (op.url !== undefined) it.url = op.url
      if (op.kind !== undefined) it.kind = op.kind
      if (op.reason) it.reason = op.reason
      it.changed_turn = turn
    } else if (op.op === 'link.remove') {
      m.links = m.links.filter(item => item.id !== op.id)
    } else if (op.op === 'last_turn.set') {
      m.last_turn = { bullets: [...op.bullets], turn }
    } else if (op.op === 'headsup.upsert') {
      if (op.id === undefined) {
        m.headsup.push({
          id: mint('h'), sev: op.sev ?? 'flag', what: op.what ?? '', why: op.why ?? '', where: op.where ?? '',
          order: m.seq, created_turn: turn, changed_turn: turn, reason: op.reason,
        })
        continue
      }
      const it = m.headsup.find(item => item.id === op.id)
      if (!it) continue
      if (op.sev !== undefined) it.sev = op.sev
      if (op.what !== undefined) it.what = op.what
      if (op.why !== undefined) it.why = op.why
      if (op.where !== undefined) it.where = op.where
      it.changed_turn = turn
      if (op.reason) it.reason = op.reason
    } else if (op.op === 'freeform.upsert') {
      const body = bodies[op.bodyRef]
      if (body === undefined) continue
      const hash = hashOf(body)
      if (op.id === undefined) {
        m.freeform.push({ id: mint('f'), body, hash, changed_turn: turn, dismissed_turn: 0, reason: op.reason })
        continue
      }
      const it = m.freeform.find(item => item.id === op.id)
      if (!it || it.hash === hash) continue
      it.body = body
      it.hash = hash
      it.changed_turn = turn
      if (op.reason) it.reason = op.reason
    }
  }
  m.turn = turn
  return m
}

/** The user's verdicts applied to a copy of the board, without turn stamps; unknown ids are skipped. */
export function applyVerdicts(board: Board, verdicts: Record<string, VerdictRecord>): Board {
  const m = clone(board)
  for (const [key, entry] of Object.entries(verdicts)) {
    const [section, id] = splitVerdictKey(key)
    if (section === 'todo' && entry.verdict === 'done') {
      for (const it of m.todo) {
        if (it.id !== id) continue
        it.status = 'done'
        if (entry.turn) it.done_turn = int(entry.turn)
      }
    } else if (section === 'todo' && entry.verdict === 'dropped') {
      m.todo = m.todo.filter(it => it.id !== id)
    } else if (section === 'cta' && entry.verdict === 'dismissed') {
      m.cta = m.cta.filter(it => it.id !== id)
    } else if (section === 'freeform' && entry.verdict === 'dismissed') {
      for (const it of m.freeform) if (it.id === id && !it.dismissed_turn) it.dismissed_turn = int(entry.turn) || m.turn || 1
    }
  }
  return m
}

/**
 * The acks and verdicts to keep beside a new board: an ack while its heads-up row lives; a verdict until the board
 * itself carries its effect, the newest 50. A dropped or dismissed item's verdict stays as the never-re-add memory.
 */
export function keptBeside(board: Board, acks: Record<string, Ack>, verdicts: Record<string, VerdictRecord>) {
  const liveRows = new Set(board.headsup.map(it => it.id))
  const todoStatus = new Map(board.todo.map(it => [it.id, it.status]))
  const cardDismissed = new Map(board.freeform.map(it => [it.id, it.dismissed_turn]))
  const isAbsorbed = (key: string, entry: VerdictRecord) => {
    const [section, id] = splitVerdictKey(key)
    if (entry.verdict === 'done') return !todoStatus.has(id) || todoStatus.get(id) === 'done'
    if (section === 'freeform') return !cardDismissed.has(id) || (cardDismissed.get(id) ?? 0) > 0
    return false
  }
  const kept = Object.entries(verdicts).filter(([key, entry]) => !isAbsorbed(key, entry))
  const newest = kept.sort(([, a], [, b]) => (a.at ?? 0) - (b.at ?? 0)).slice(-MAX_VERDICTS)
  return {
    acks: Object.fromEntries(Object.entries(acks).filter(([id]) => liveRows.has(id))),
    verdicts: Object.fromEntries(newest),
  }
}
