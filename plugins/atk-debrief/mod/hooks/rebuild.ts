// The chat's dashboard kept by the session itself: its turns recorded as they end, the board rebuilt from them with
// the session's own model access, and the user's presses saved. state.json beside the chat holds the board; tail-0/1/2
// .json hold its last turns.

import type { ModelCompleteRequest, ModelCompleteResult, SessionMessage } from 'claude-code'

import { AnswerError, parseAnswer } from './answer'
import { type Ack, applyOps, applyVerdicts, boardAt, boardOf, guardOps, keptBeside, verdictKeyOf, type VerdictRecord } from './board'
import { assemblePrompt, retryPromptOf, type TurnRecord } from './prompt'
import { codeOfApiError, isPassing, type RebuildError, type RebuildStats, resolvedErrors, withError } from './status'
import { earlierPromptsOf, forkPointOf, latestTurnOf, type PendingPrompt, recordableOf, squeezed, startOf, TAIL_SLOTS, tailOf, tailPathOf, tailRecordOf, turnsOf } from './turns'

/** A chat's place on disk: its project folder's name, its session id, and the folder beside its transcript. */
export type Chat = { project: string; session: string; dir: string }

/** What the mod knows of the chat's turns: how many, when the last ended, and each prompt's fingerprint. */
type TurnState = { count: number; endedAt: number; prompts: string[] }

export type StoredState = {
  version?: number
  model?: unknown
  acks?: Record<string, Ack>
  verdicts?: Record<string, VerdictRecord>
  regenErrors?: RebuildError[]
  parent?: unknown
  parentChecked?: boolean
  turns?: TurnState
  rebuiltAt?: number
  stats?: RebuildStats
}

export type Settings = { model: string; timeoutSeconds: number }

/** What the rebuild reaches outside itself, built over `$` in register.tsx, so this file holds no `$` of its own. */
export type Io = {
  pluginRoot: string
  exists: (path: string) => Promise<boolean>
  list: (path: string) => Promise<{ name: string; kind: string }[]>
  read: (path: string) => Promise<string>
  write: (path: string, text: string) => Promise<void>
  nowMs: () => Promise<number>
  sleep: (ms: number) => Promise<void>
  complete: (request: ModelCompleteRequest) => Promise<ModelCompleteResult>
  storeGet: (key: string) => Promise<unknown>
  storeSet: (key: string, value: unknown) => Promise<void>
}

const DEFAULT_SETTINGS: Settings = { model: 'haiku', timeoutSeconds: 60 }
// The longest answer a rebuild may write; real ones stay under 21,000 tokens.
const MAX_ANSWER_TOKENS = 32_000
// How long a model too busy to answer gets before it is asked again.
const RETRY_WAIT_MS = 5_000
// Fingerprints kept for finding where a fork left its parent.
const MAX_PROMPTS = 2_000

const isObject = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value)

const statePathOf = (chat: Chat) => `${chat.dir}/state.json`

/** A state.json that does not parse, read twice; `text` is what it holds. */
export class StateUnreadable extends Error {
  constructor(readonly text: string) {
    super('state.json does not parse')
  }
}

// claude-dashboard saved a problem without its code, count or last time, and at first without a resolved time; the kind
// it named the failure by gives the code.
const errorOf = (error: Partial<RebuildError> & Pick<RebuildError, 'id' | 'at' | 'kind' | 'message'>): RebuildError => ({
  ...error,
  lastAt: error.lastAt ?? error.at,
  count: error.count ?? 1,
  code: error.code ?? (error.kind === 'RegenTimeout' ? 'rebuild.timeout' : 'rebuild.failed'),
  ackedAt: error.ackedAt ?? null,
  resolvedAt: error.resolvedAt ?? null,
})

const parsedOf = (text: string): StoredState | null => {
  try {
    const data: unknown = JSON.parse(text)
    if (!isObject(data)) return null
    const state = data as StoredState
    return Array.isArray(state.regenErrors) ? { ...state, regenErrors: state.regenErrors.map(errorOf) } : state
  } catch {
    return null
  }
}

/**
 * The chat's state.json; none for a chat the mod has not saved yet. A file that does not parse is read once more, as
 * a read can land while another process writes it; one that still does not parse throws StateUnreadable.
 */
export async function readState(io: Io, chat: Chat): Promise<StoredState> {
  if (!(await io.exists(statePathOf(chat)))) return {}
  const first = parsedOf(await io.read(statePathOf(chat)))
  if (first) return first
  const text = await io.read(statePathOf(chat))
  const second = parsedOf(text)
  if (second) return second
  throw new StateUnreadable(text)
}

// A state.json that is damaged for good is kept beside it, for the person to look at, and a save starts afresh.
async function stateOrFresh(io: Io, chat: Chat): Promise<StoredState> {
  try {
    return await readState(io, chat)
  } catch (error) {
    if (!(error instanceof StateUnreadable)) throw error
    await io.write(`${statePathOf(chat)}.damaged`, error.text)
    return {}
  }
}

// One change to a chat's state.json at a time in this session, so each reads the file as the one before it left it.
const queues = new Map<string, Promise<unknown>>()

function exclusive<T>(chat: Chat, work: () => Promise<T>): Promise<T> {
  const path = statePathOf(chat)
  const run = (queues.get(path) ?? Promise.resolve()).then(work, work)
  queues.set(
    path,
    run.catch(() => {}),
  )
  return run
}

// Writes the change on the file as it is now; call it only inside `exclusive`.
async function writeChange(io: Io, chat: Chat, change: (state: StoredState) => StoredState): Promise<void> {
  const state = change(await stateOrFresh(io, chat))
  await io.write(statePathOf(chat), JSON.stringify({ ...state, version: 1 }, null, 2))
}

/** Saves the change on the file as it is now, so a press saved meanwhile stays; rejects when the write fails. */
const changeState = (io: Io, chat: Chat, change: (state: StoredState) => StoredState) => exclusive(chat, () => writeChange(io, chat, change))

const nowSecondsOf = async (io: Io) => Math.floor((await io.nowMs()) / 1000)

async function sha256Of(text: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))
  return [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, '0')).join('')
}

const fingerprintOf = async (text: string) => (await sha256Of(text)).slice(0, 12)

function errorIdOf(nowSeconds: number): string {
  const bytes = crypto.getRandomValues(new Uint8Array(4))
  return `err-${nowSeconds}-${[...bytes].map(byte => byte.toString(16).padStart(2, '0')).join('')}`
}

// The longest time limit, in seconds: Claude Code's model call takes no more than a timer holds, 2147483647 ms.
const MAX_TIMEOUT_SECONDS = Math.floor(2_147_483_647 / 1000)
const isTimeLimit = (seconds: unknown) => Number.isInteger(seconds) && (seconds as number) >= 1 && (seconds as number) <= MAX_TIMEOUT_SECONDS

const isSettings = (value: unknown): value is Settings =>
  isObject(value) && typeof value.model === 'string' && value.model !== '' && isTimeLimit(value.timeoutSeconds)

/** A setting the person entered that cannot be used; its message says what can. */
export class SettingsError extends Error {}

// A model's alias or full id, as Claude Code's --model takes it (`sonnet`, `claude-haiku-5-5`, `opus[1m]`).
const MODEL_NAME = /^[A-Za-z0-9][A-Za-z0-9._\-[\]]{0,99}$/

/** The settings with the change in it, checked; a SettingsError says why one cannot be used. */
function settingsWith(settings: Settings, change: { model?: string; timeoutSeconds?: string }): Settings {
  const next = { ...settings }
  if (change.model !== undefined) {
    const model = change.model.trim()
    if (!MODEL_NAME.test(model)) throw new SettingsError('A model is a name such as sonnet, or a full id such as claude-haiku-5-5.')
    next.model = model
  }
  if (change.timeoutSeconds !== undefined) {
    const seconds = Number(change.timeoutSeconds.trim())
    if (!isTimeLimit(seconds)) {
      throw new SettingsError(`The time limit is a whole number of seconds, from 1 up to ${MAX_TIMEOUT_SECONDS}, the most Claude Code takes.`)
    }
    next.timeoutSeconds = seconds
  }
  return next
}

// Claude Code's own model choices that do not suit a rebuild: the session's default, a plan mode, `best` (whatever
// model is the most capable, at its price), and the 1M-context variants, since a rebuild prompt stays far below 200K.
const isForARebuild = (model: string) => !['default', 'opusplan', 'best'].includes(model) && !model.endsWith('[1m]')
// What the picker offers when Claude Code lists no models.
const FALLBACK_MODELS = ['haiku', 'sonnet', 'opus']

/**
 * The models the settings offer: the current one first, so a pick that does not move keeps it, then the model
 * families Claude Code's own model setting lists (its `model` config row), so a new family shows up without a change
 * here.
 */
export function modelChoicesOf(current: string, offered: readonly string[] | null): string[] {
  const listed = (offered ?? []).filter(isForARebuild)
  return [current, ...(listed.length > 0 ? listed : FALLBACK_MODELS).filter(model => model !== current)]
}

// The call that asks whether Claude Code reaches a model, within 15 seconds. It asks for as much output as a rebuild
// does, so a model that cannot write that much is refused here, not at every rebuild; the reply is still "OK".
const MODEL_CHECK_SECONDS = 15
const MODEL_CHECK = { prompt: 'Reply with OK.', maxTokens: MAX_ANSWER_TOKENS, timeoutMs: MODEL_CHECK_SECONDS * 1000 }

/** Why Claude Code could not tell whether it reaches the model, or null when it could; a model it has none of throws. */
async function uncheckedOf(io: Io, model: string): Promise<string | null> {
  const reply = await io.complete({ model, ...MODEL_CHECK })
  if (reply.isAnswered || reply.reason === 'empty-reply') return null
  if (reply.reason === 'aborted') return `no answer in ${MODEL_CHECK_SECONDS} seconds`
  if (reply.error === 'model_not_found') throw new SettingsError(`Claude Code finds no model ${model} for this account. Nothing is saved.`)
  return reply.error
}

/** The settings a save stored, and why a new model in them could not be checked, if it could not. */
type SavedSettings = { settings: Settings; unchecked: string | null }

/** Saves the change for every chat once a new model is checked; the next rebuild uses it. Rejects when the store cannot be written. */
export async function saveSettings(io: Io, change: { model?: string; timeoutSeconds?: string }): Promise<SavedSettings> {
  const current = await settingsOf(io)
  const next = settingsWith(current, change)
  const unchecked = next.model === current.model ? null : await uncheckedOf(io, next.model)
  // A change saved while the model was checked stays: this save applies only what it changes.
  const saved = settingsWith(await settingsOf(io), change)
  await io.storeSet('settings', saved)
  return { settings: saved, unchecked }
}

/** The settings every chat's rebuilds use: what the settings pane saved, else Haiku for at most 60 seconds. */
export async function settingsOf(io: Io): Promise<Settings> {
  const stored = await io.storeGet('settings')
  return isSettings(stored) ? stored : { ...DEFAULT_SETTINGS }
}

const turnOfEntry = (entry: string) => Number(entry.slice(0, entry.indexOf(':')))

/** How many recorded turns the dashboard does not hold yet: all of them before its first build. */
export const unbuiltTurnsOf = (state: StoredState) => (state.turns ? Math.max(0, state.turns.count - (state.model ? boardOf(state.model).turn : 0)) : 0)

/**
 * The state a fork starts from: the board of the chat its earlier messages came from as it stood at the fork, with
 * that chat's turn count there and its tail files up to it. Null when no chat in the project shares enough of them.
 */
async function forkedStateOf(io: Io, chat: Chat, earlier: string[]): Promise<StoredState | null> {
  if (earlier.length === 0) return null
  // A fingerprint is of the prompt's squeezed text; one saved before that is of its text as given, so both count.
  const pairs = await Promise.all(earlier.map(async text => [await fingerprintOf(squeezed(text)), await fingerprintOf(text)] as const))
  const projectDir = chat.dir.slice(0, chat.dir.lastIndexOf('/'))
  let best: { session: string; state: StoredState; turn: number; shared: number } | null = null
  for (const entry of await io.list(projectDir)) {
    if (entry.kind !== 'dir' || entry.name === chat.session) continue
    const sibling: Chat = { project: chat.project, session: entry.name, dir: `${projectDir}/${entry.name}` }
    const state = await readState(io, sibling).catch(() => ({}) as StoredState)
    const known = new Set((state.turns?.prompts ?? []).map(entry => entry.slice(entry.indexOf(':') + 1)))
    const point = forkPointOf(
      pairs.map(([squeezedHash, rawHash]) => (known.has(squeezedHash) ? squeezedHash : rawHash)),
      state.turns?.prompts ?? [],
    )
    if (point && (!best || point.shared > best.shared || (point.shared === best.shared && point.turn > best.turn))) best = { session: entry.name, state, ...point }
  }
  if (!best) return null
  const parentDir = `${projectDir}/${best.session}`
  for (let turn = Math.max(1, best.turn - TAIL_SLOTS + 1); turn <= best.turn; turn++) {
    const path = tailPathOf(parentDir, turn)
    if (!(await io.exists(path))) continue
    const text = await io.read(path)
    if (tailRecordOf(text, turn)) await io.write(tailPathOf(chat.dir, turn), text)
  }
  return {
    model: best.state.model ? boardAt(boardOf(best.state.model), best.turn) : undefined,
    acks: best.state.acks ?? {},
    verdicts: best.state.verdicts ?? {},
    parent: { session: best.session, branchTurn: best.turn },
    turns: { count: best.turn, endedAt: 0, prompts: (best.state.turns?.prompts ?? []).filter(entry => turnOfEntry(entry) <= best.turn) },
  }
}

/**
 * A chat new to the mod whose messages came from another chat (a fork) takes that chat's board, as it stood at the
 * fork, and its turn count there at once, so its band shows them before its own first turn. Saves nothing for a chat
 * that is no fork. Resolves whether it took one.
 */
export function adoptFork(io: Io, chat: Chat, messages: SessionMessage[]): Promise<boolean> {
  return exclusive(chat, async () => {
    if (await io.exists(statePathOf(chat))) return false
    const forked = await forkedStateOf(io, chat, earlierPromptsOf(messages, []))
    if (!forked) return false
    await writeChange(io, chat, fresh => ({ ...fresh, ...forked, parentChecked: true }))
    return true
  })
}

/**
 * Records the turns the pending prompts opened, each cut from `messages`: the count goes up by one per prompt and the
 * newest turns go into the tail files. A prompt typed over the running turn that the messages do not hold yet waits
 * for its own turn. With no prompt to record (a turn a task notice started), the newest turn is cut again from
 * `lastPrompt`, the prompt it was recorded from, to the end, so it holds what that turn added. A chat new to the mod
 * whose messages came from another chat (a fork) first takes that chat's board and count. Resolves to how many of the
 * pending prompts it recorded.
 */
export function recordTurns(io: Io, chat: Chat, pending: PendingPrompt[], messages: SessionMessage[], lastPrompt: string | null): Promise<number> {
  return exclusive(chat, async () => {
    const recordable = recordableOf(messages, pending, lastPrompt)
    const prompts = pending.slice(0, recordable).map(prompt => prompt.text)
    let state = await stateOrFresh(io, chat)
    if (!state.turns && !state.model && !state.parentChecked) {
      const forked = await forkedStateOf(io, chat, earlierPromptsOf(messages, prompts))
      state = { ...state, ...forked, parentChecked: true }
    }
    const turns: TurnState = state.turns ?? { count: boardOf(state.model).turn, endedAt: 0, prompts: [] }
    let count = turns.count
    const fingerprints = [...turns.prompts]
    if (prompts.length > 0) {
      const cut = turnsOf(messages, prompts, lastPrompt === null ? -1 : startOf(messages, lastPrompt))
      for (const [index, rows] of cut.entries()) {
        count += 1
        fingerprints.push(`${count}:${await fingerprintOf(squeezed(prompts[index] ?? ''))}`)
        if (index >= cut.length - TAIL_SLOTS) await io.write(tailPathOf(chat.dir, count), JSON.stringify(tailOf(count, rows)))
      }
    } else if (lastPrompt !== null && count > 0) {
      const rows = latestTurnOf(messages, lastPrompt)
      if (rows) await io.write(tailPathOf(chat.dir, count), JSON.stringify(tailOf(count, rows)))
    }
    const endedAt = await nowSecondsOf(io)
    const seeded = { model: state.model, acks: state.acks, verdicts: state.verdicts, parent: state.parent, parentChecked: state.parentChecked }
    await writeChange(io, chat, fresh => ({
      ...(fresh.model ? fresh : { ...fresh, ...seeded }),
      turns: { count, endedAt, prompts: fingerprints.slice(-MAX_PROMPTS) },
    }))
    return recordable
  })
}

async function tailRecordsOf(io: Io, chat: Chat, count: number): Promise<TurnRecord[]> {
  const records: TurnRecord[] = []
  for (let turn = Math.max(1, count - TAIL_SLOTS + 1); turn <= count; turn++) {
    const path = tailPathOf(chat.dir, turn)
    if (!(await io.exists(path))) continue
    const record = tailRecordOf(await io.read(path), turn)
    if (record) records.push(record)
  }
  return records
}

export type Rebuilt = { outcome: 'rebuilt'; ops: number; notes: string[] } | { outcome: 'failed'; code: string } | { outcome: 'skipped'; why: string }

type Failure = { code: string; kind: string; message: string }

async function recordFailure(io: Io, chat: Chat, failure: Failure): Promise<Rebuilt> {
  const now = await nowSecondsOf(io)
  await changeState(io, chat, fresh => ({ ...fresh, regenErrors: withError(fresh.regenErrors ?? [], failure, now, () => errorIdOf(now)) }))
  return { outcome: 'failed', code: failure.code }
}

/**
 * Rebuilds the chat's board from its last turns, within one time limit. The model answers with a change set; a
 * rejected answer goes back once with the reason, and a model too busy to answer is asked once more after a wait. A
 * failure leaves the board as it was and is kept as an error the band shows; a later success resolves it. The board
 * saved takes the user's calls as they are when it saves, so a press or an undo made meanwhile stays. Rejects only
 * when state.json cannot be written.
 */
export async function rebuildChat(io: Io, chat: Chat, settings: Settings): Promise<Rebuilt> {
  // Read as a save would, so a press saving meanwhile is never read half written.
  const state = await exclusive(chat, () => stateOrFresh(io, chat))
  // A chat whose count is not saved yet counts from its board's last turn, as recordTurns does.
  const count = state.turns?.count ?? boardOf(state.model).turn
  const records = await tailRecordsOf(io, chat, count)
  if (records.length === 0) return { outcome: 'skipped', why: 'no turn of this chat is recorded yet' }

  const verdicts = state.verdicts ?? {}
  const raw = boardOf(state.model)
  // The model reads the board with the user's calls applied; its changes fold into the board as stored, and the calls
  // apply again when it saves.
  const shown = Object.keys(verdicts).length > 0 ? applyVerdicts(raw, verdicts) : raw
  const prompt = assemblePrompt({
    board: shown,
    turns: records,
    turn: count,
    systemTemplate: await io.read(`${io.pluginRoot}/SYSTEM.md`),
    verdicts,
    acks: state.acks ?? {},
  })

  const timeoutMs = settings.timeoutSeconds * 1000
  const timedOut = () => recordFailure(io, chat, { code: 'rebuild.timeout', kind: 'timeout', message: `the model call ran past ${settings.timeoutSeconds}s and was stopped` })
  const firstStartedAt = await io.nowMs()
  let deadline: number | null = null
  let user = prompt.user
  // A rejected answer goes back once, and a busy model is asked once more; each on its own count.
  let isCorrected = false
  let isAskedAgain = false
  const correct = (answer: string, reason: string) => {
    if (isCorrected) return recordFailure(io, chat, { code: 'rebuild.bad_output', kind: 'rejected', message: `the corrected answer was rejected too: ${reason}` })
    isCorrected = true
    user = prompt.user + retryPromptOf(answer, reason)
    return null
  }
  const spent: Spent = { input: 0, cachedInput: 0, output: 0 }
  for (;;) {
    const startedAt = await io.nowMs()
    deadline ??= startedAt + timeoutMs
    const attemptMs = deadline - startedAt
    if (attemptMs < 1000) return timedOut()
    let reply: ModelCompleteResult
    try {
      reply = await io.complete({ model: settings.model, system: prompt.system, prompt: user, maxTokens: MAX_ANSWER_TOKENS, timeoutMs: attemptMs })
    } catch (error) {
      // Claude Code sends no request it refuses: a model it blocks, an output limit past the model's own.
      return recordFailure(io, chat, { code: 'rebuild.refused', kind: 'refused', message: `Claude Code refused to send the request: ${(error as Error).message}` })
    }
    // Cached input counts toward what the prompt weighed.
    const cached = (reply.usage.cache_read_input_tokens ?? 0) + (reply.usage.cache_creation_input_tokens ?? 0)
    spent.input += (reply.usage.input_tokens ?? 0) + cached
    spent.cachedInput += reply.usage.cache_read_input_tokens ?? 0
    spent.output += reply.usage.output_tokens ?? 0
    if (!reply.isAnswered) {
      if (reply.reason === 'aborted') {
        // Cut short before its time (a reload, a quit) it is no failure of the rebuild's.
        if ((await io.nowMs()) - startedAt < attemptMs - 1000) return { outcome: 'skipped', why: 'cancelled' }
        return timedOut()
      }
      if (reply.reason === 'empty-reply') {
        const failed = correct('', 'the reply had no text')
        if (failed) return failed
        continue
      }
      // A busy model is asked once more after a wait, when the time limit leaves room for the wait and an answer.
      if (!isAskedAgain && isPassing(reply.error) && deadline - (await io.nowMs()) >= RETRY_WAIT_MS + 1000) {
        isAskedAgain = true
        await io.sleep(RETRY_WAIT_MS)
        continue
      }
      return recordFailure(io, chat, { code: codeOfApiError(reply.error), kind: reply.error, message: `the model call failed: ${reply.error}${reply.status ? ` (HTTP ${reply.status})` : ''}` })
    }
    try {
      const { update, bodies, notes } = parseAnswer(reply.text)
      const hashes = new Map<string, string>()
      for (const body of Object.values(bodies)) hashes.set(body, (await sha256Of(body)).slice(0, 12))
      const now = await nowSecondsOf(io)
      const wallMs = (await io.nowMs()) - firstStartedAt
      await changeState(io, chat, fresh => {
        // What is locked is judged as the state stands now, so an ack or a check made while the model ran counts.
        const guarded = guardOps(raw, update, fresh.acks ?? {}, fresh.verdicts ?? {})
        const folded = applyOps(raw, guarded.update, bodies, count, body => hashes.get(body) ?? '')
        // The calls the model read, less any the user took back meanwhile; one made meanwhile waits beside the board
        // for the next rebuild, which reads it.
        const calls = Object.fromEntries(Object.entries(verdicts).filter(([key, call]) => fresh.verdicts?.[key]?.verdict === call.verdict))
        const rebuilt = Object.keys(calls).length > 0 ? applyVerdicts(folded, calls) : folded
        return {
          ...fresh,
          model: rebuilt,
          ...keptBeside(rebuilt, fresh.acks ?? {}, fresh.verdicts ?? {}),
          regenErrors: resolvedErrors(fresh.regenErrors ?? [], now),
          rebuiltAt: now,
          stats: withRebuild(fresh.stats, spent, wallMs, settings.model, guarded),
        }
      })
      return { outcome: 'rebuilt', ops: update.ops.length, notes }
    } catch (error) {
      if (!(error instanceof AnswerError)) throw error
      const failed = correct(reply.text, error.message)
      if (failed) return failed
    }
  }
}

type Spent = { input: number; cachedInput: number; output: number }

function withRebuild(stats: Partial<RebuildStats> | undefined, spent: Spent, wallMs: number, model: string, guarded: { ignored: number; repairs: number }): RebuildStats {
  const models = stats?.models ?? []
  const ignoredOps = (stats?.ignoredOps ?? 0) + guarded.ignored
  const repairOps = (stats?.repairOps ?? 0) + guarded.repairs
  return {
    rebuilds: (stats?.rebuilds ?? 0) + 1,
    inputTokens: (stats?.inputTokens ?? 0) + spent.input,
    cachedInputTokens: (stats?.cachedRebuilds === undefined ? 0 : (stats.cachedInputTokens ?? 0)) + spent.cachedInput,
    cachedRebuilds: (stats?.cachedRebuilds ?? 0) + 1,
    outputTokens: (stats?.outputTokens ?? 0) + spent.output,
    wallMs: (stats?.wallMs ?? 0) + wallMs,
    models: models.includes(model) ? models : [...models, model],
    ...(ignoredOps > 0 ? { ignoredOps } : {}),
    ...(repairOps > 0 ? { repairOps } : {}),
  }
}

// ─── The user's presses ──────────────────────────────────────────────

export type Section = 'cta' | 'todo' | 'freeform' | 'links'

// The calls the user can make on an item of each section.
const CALLS = { todo: ['done', 'dropped'], cta: ['dismissed'], freeform: ['dismissed'], links: ['dismissed'] } as const satisfies Record<Section, readonly string[]>

/** A call on an item of the section: a dismissed ask, card or link, a step done or dropped. */
export type CallOf<S extends Section> = (typeof CALLS)[S][number]

type CalledItem = { id: string; text?: string; label?: string; url?: string; reason: string }

// A link has no text of its own: the rebuild knows it by its label and address.
const wordingOf = (item: CalledItem | undefined) => (item?.label ? `${item.label} ${item.url}` : item?.text) || item?.reason || ''

/**
 * The user's call on an item, kept with its wording and the board's turn so the next rebuild reads it as a fact;
 * null takes it back. Rejects when state.json cannot be written, so a press never passes for saved.
 */
export async function setVerdict<S extends Section>(io: Io, chat: Chat, section: S, id: string, verdict: CallOf<S> | null): Promise<void> {
  if (verdict !== null && !(CALLS[section] as readonly string[]).includes(verdict)) throw new Error(`${verdict} is no call on a ${section} item`)
  const now = await nowSecondsOf(io)
  await changeState(io, chat, fresh => {
    const verdicts = { ...(fresh.verdicts ?? {}) }
    const key = verdictKeyOf(section, id)
    if (verdict === null) {
      delete verdicts[key]
    } else {
      const board = boardOf(fresh.model)
      const item = (board[section] as CalledItem[]).find(it => it.id === id)
      verdicts[key] = { verdict, at: now, turn: board.turn, text: wordingOf(item) }
    }
    return { ...fresh, verdicts }
  })
}

/** A heads-up row acknowledged, with when and at which turn, or no longer. */
export async function setAcknowledged(io: Io, chat: Chat, rowId: string, isAcknowledged: boolean): Promise<void> {
  const now = await nowSecondsOf(io)
  await changeState(io, chat, fresh => {
    const acks = { ...(fresh.acks ?? {}) }
    if (isAcknowledged) acks[rowId] = { ackedAt: now, turn: boardOf(fresh.model).turn }
    else delete acks[rowId]
    return { ...fresh, acks }
  })
}

/** A problem dismissed by the user, or brought back. */
export async function setProblemDismissed(io: Io, chat: Chat, errorId: string, isDismissed: boolean): Promise<void> {
  const now = await nowSecondsOf(io)
  await changeState(io, chat, fresh => ({
    ...fresh,
    regenErrors: (fresh.regenErrors ?? []).map(error => (error.id === errorId ? { ...error, ackedAt: isDismissed ? now : null } : error)),
  }))
}
