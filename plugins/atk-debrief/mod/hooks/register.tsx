import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, SessionMessage } from 'claude-code'

import type { DebriefBand } from '../types'
import { drawBand, viewsOf } from './band'
import { bandOf, firstBuildOf, isLiveCard, quoteOf } from './band-model'
import { cardPagesOf, drawCards, drawSettings } from './panes'
import {
  adoptFork,
  type CallOf,
  type Chat,
  type Io,
  modelChoicesOf,
  readState,
  rebuildChat,
  recordTurns,
  saveSettings,
  type Section,
  type Settings,
  SettingsError,
  setAcknowledged,
  setProblemDismissed,
  settingsOf,
  setVerdict,
  StateUnreadable,
  type StoredState,
  unbuiltTurnsOf,
} from './rebuild'
import { hasSettingsFix, SETTINGS_COMMAND, statusOf } from './status'
import { isUsersOwn, type PendingPrompt } from './turns'

const POLL_MS = 2_000

const bandAtom = atom({ plugin: 'atk-debrief', key: 'band' } as const, null)
// The view open under the header, one at a time.
const openViewAtom = atom({ plugin: 'atk-debrief', key: 'openView' } as const, null)
const isAckedOpenAtom = atom({ plugin: 'atk-debrief', key: 'isAckedOpen' } as const, false)
const isDoneOpenAtom = atom({ plugin: 'atk-debrief', key: 'isDoneOpen' } as const, false)
// Whether the band shows only its header line.
const isBandFoldedAtom = atom({ plugin: 'atk-debrief', key: 'isBandFolded' } as const, false)
const openNoticeIdsAtom = atom({ plugin: 'atk-debrief', key: 'openNoticeIds' } as const, [])
const isResolvedOpenAtom = atom({ plugin: 'atk-debrief', key: 'isResolvedOpen' } as const, false)
const isFreeformOpenAtom = atom({ plugin: 'atk-debrief', key: 'isFreeformOpen' } as const, false)
const isFreeformDismissedOpenAtom = atom({ plugin: 'atk-debrief', key: 'isFreeformDismissedOpen' } as const, false)
// The page of cards the pane shows, when they are more than one drawing holds.
const freeformPageAtom = atom({ plugin: 'atk-debrief', key: 'freeformPage' } as const, 0)
// The live cards, as "id@turn changed", when the pane last opened by itself or the person closed it.
const freeformSeenAtom = atom({ plugin: 'atk-debrief', key: 'freeformSeen' } as const, [])
// The user's prompts since the last recorded turn end, and the prompt the newest recorded turn opened with, kept
// across a reload of the mod.
const pendingPromptsAtom = atom({ plugin: 'atk-debrief', key: 'pendingPrompts' } as const, [])
const lastPromptAtom = atom({ plugin: 'atk-debrief', key: 'lastPrompt' } as const, null)
// Whether this session ever drew the band: a headless run never does, and never records or rebuilds.
const hasDrawnAtom = atom({ plugin: 'atk-debrief', key: 'hasDrawn' } as const, false)

// The settings as the settings pane shows them.
const settingsShownAtom = atom({ plugin: 'atk-debrief', key: 'settingsShown' } as const, null)
// What the last change in each settings field came to, drawn under that field.
const settingsNotesAtom = atom({ plugin: 'atk-debrief', key: 'settingsNotes' } as const, { model: null, timeout: null })
// Counts the picks from the model list; each draws the Other model field anew, empty.
const modelIdRowAtom = atom({ plugin: 'atk-debrief', key: 'modelIdRow' } as const, 0)
// The model being checked before it is saved; the picker shows it meanwhile.
const modelCheckingAtom = atom({ plugin: 'atk-debrief', key: 'modelChecking' } as const, null)

// Prompts kept while the band is not drawn yet, so a long headless run does not grow them without end.
const MAX_PENDING = 50

// The side pane that holds the chat's Freeform cards.
const FREEFORM_PANE = 'debrief-freeform'
// The pane that sets the model and the time limit, and the command that opens it.
const SETTINGS_PANE = 'debrief-settings'

let located: Chat | null = null

async function locateChat($: EngineInterface): Promise<Chat | null> {
  const session = await $.session.id()
  if (located?.session === session) return located

  // Claude Code keeps its chats under CLAUDE_CONFIG_DIR when it is set, else under ~/.claude.
  const configDir = (await $.env.get('CLAUDE_CONFIG_DIR')) || `${await $.env.get('HOME')}/.claude`
  const projects = `${configDir}/projects`
  // A folder that is not there yet holds no chat.
  for (const entry of await $.fs.list(projects).catch(() => [])) {
    if (entry.kind === 'dir' && (await $.fs.exists(`${projects}/${entry.name}/${session}.jsonl`))) {
      located = { project: entry.name, session, dir: `${projects}/${entry.name}/${session}` }
      return located
    }
  }
  return null
}

// The files, clock, model and store the rebuild reaches, through this session's `$`.
function ioOf($: EngineInterface): Io {
  return {
    pluginRoot: $.plugin.root,
    exists: path => $.fs.exists(path),
    list: path => $.fs.list(path),
    read: path => $.fs.read(path),
    write: (path, text) => $.fs.write(path, text),
    nowMs: () => $.clock.now(),
    sleep: ms => $.clock.sleep(ms),
    complete: request => $.model.complete(request),
    storeGet: key => $.store.get(key),
    storeSet: (key, value) => $.store.set(key, value),
  }
}

/** The chat's messages since its last compaction, or none when the engine refuses them. */
async function messagesOf($: EngineInterface): Promise<SessionMessage[]> {
  const messages = await $.session.messages()
  return Array.isArray(messages) ? (messages as SessionMessage[]) : []
}

// The rebuild this session runs, one at a time; a turn ending meanwhile asks for one more after it, of the chat it
// ended in. Its start is null until it starts, and it reads as starting now until then.
let rebuilding: { since: number | null } | null = null
let rerunChat: Chat | null = null

// The chat's state.json as the band last parsed it, kept while its size and change time stay.
let stateRead: { stamp: string; state: StoredState } | null = null

async function bandStateOf($: EngineInterface, chat: Chat): Promise<StoredState> {
  const stat = await $.fs.stat(`${chat.dir}/state.json`).catch(() => null)
  const stamp = stat && `${chat.dir} ${stat.size} ${stat.mtimeMs}`
  if (stamp && stateRead?.stamp === stamp) return stateRead.state
  try {
    const state = await readState(ioOf($), chat)
    stateRead = stamp ? { stamp, state } : null
    return state
  } catch (error) {
    // A file that does not parse shows the band as it last read it, until a save puts the file right.
    if (!(error instanceof StateUnreadable)) throw error
    return stateRead?.state ?? {}
  }
}

async function readBand($: EngineInterface): Promise<DebriefBand | null> {
  const chat = await locateChat($)
  if (!chat) return null
  const state = await bandStateOf($, chat)
  const now = (await $.clock.now()) / 1000
  const status = statusOf(
    {
      runningSince: rebuilding ? (rebuilding.since ?? now) : null,
      rebuiltAt: state.rebuiltAt ?? null,
      unbuiltTurns: unbuiltTurnsOf(state),
      errors: state.regenErrors ?? [],
      ...(state.stats ? { stats: state.stats } : {}),
    },
    now,
  )
  if (!state.model) return firstBuildOf(status)
  return bandOf(state, status)
}

async function refresh($: EngineInterface): Promise<void> {
  const next = await readBand($)
  if (JSON.stringify(await read($, bandAtom)) === JSON.stringify(next)) return
  await update($, bandAtom, () => next)
  // A view whose content went away closes, so it does not open by itself when content comes back.
  const view = await read($, openViewAtom)
  if (next && view && !viewsOf(next)[view]) await update($, openViewAtom, () => null)
  await openFreeformOnNewCards($, next)
}

// ❝: the item quoted into the prompt box, every line of it, on lines of its own after what the box holds.
async function quote($: EngineInterface, text: string): Promise<void> {
  const { text: draft } = await $.prompt.read()
  const lead = draft.trim() === '' ? '' : draft.endsWith('\n\n') ? '' : draft.endsWith('\n') ? '\n' : '\n\n'
  const filled = await $.prompt.fill({ text: `${lead}${quoteOf(text)}\n\n`, mode: 'append' })
  if (filled.isFilled) return
  await $.ui.toast(filled.refusal === 'dialog' ? 'Not quoted: a dialog holds the prompt box; close it first' : 'Not quoted: the prompt box did not take it')
}

/**
 * The first draw after the mod loads: in a session's first, a fork takes the dashboard of the chat it left and the
 * turns that ended before it are recorded; and a chat whose dashboard lacks a recorded turn (one that ended while a
 * reload or a quit cut its rebuild short) rebuilds.
 */
async function catchUp($: EngineInterface): Promise<void> {
  const isFirstDraw = !(await read($, hasDrawnAtom))
  await update($, hasDrawnAtom, () => true)
  const chat = await locateChat($)
  if (!chat) return
  if (isFirstDraw) await adoptFork(ioOf($), chat, await messagesOf($)).catch(() => false)
  if (isFirstDraw && (await read($, pendingPromptsAtom)).length > 0) await recordPending($, chat)
  const state = await readState(ioOf($), chat).catch(() => ({}) as StoredState)
  if (unbuiltTurnsOf(state) > 0) scheduleRebuild($, chat)
}

// Prompts kept from before a reload of the mod that marked each as typed mid-turn or not.
const pendingOf = (list: readonly (PendingPrompt | string)[]): PendingPrompt[] =>
  list.map(entry => (typeof entry === 'string' ? { text: entry, isMidTurn: false } : entry))

// One record at a time, so two turn ends, or a first draw and a turn end, never record the same prompts twice.
let recording: Promise<unknown> = Promise.resolve()

/**
 * Records the turns the pending prompts opened. They stay pending until the record is saved, so a save that fails
 * loses none: the next turn's record takes them too; one typed over the running turn waits for its own. Resolves
 * whether it saved.
 */
function recordPending($: EngineInterface, chat: Chat): Promise<boolean> {
  const run = recording.then(async () => {
    const pending = pendingOf(await read($, pendingPromptsAtom))
    let recorded: number
    try {
      recorded = await recordTurns(ioOf($), chat, pending, await messagesOf($), await read($, lastPromptAtom))
    } catch (error) {
      await $.ui.toast(`Dashboard turn not recorded: ${(error as Error).message}`)
      return false
    }
    // A prompt sent while the record was saving stays for the next one.
    await update($, pendingPromptsAtom, list => list.slice(recorded))
    const newest = pending[recorded - 1]
    if (newest) await update($, lastPromptAtom, () => newest.text)
    return true
  })
  // A record that throws still lets the next one run.
  recording = run.catch(() => false)
  return run
}

function scheduleRebuild($: EngineInterface, chat: Chat): void {
  if (rebuilding) {
    rerunChat = chat
    return
  }
  rebuilding = { since: null }
  $.clock.after(0, () => void runRebuild($, chat))
}

async function runRebuild($: EngineInterface, chat: Chat): Promise<void> {
  rebuilding = { since: (await $.clock.now()) / 1000 }
  try {
    await refresh($)
    const rebuilt = await rebuildChat(ioOf($), chat, await settingsOf(ioOf($)))
    if (rebuilt.outcome === 'skipped' && rebuilt.why !== 'cancelled') {
      await $.ui.toast(`Dashboard not rebuilt: ${rebuilt.why}. It rebuilds when your next turn ends.`)
    }
  } catch (error) {
    await $.ui.toast(`Dashboard not saved: ${(error as Error).message}`)
  } finally {
    rebuilding = null
    const rerun = rerunChat
    rerunChat = null
    if (rerun) scheduleRebuild($, rerun)
    await refresh($).catch(() => {})
  }
}

// The pane opens by itself, without the keyboard, when a card is new or has changed since it was last seen; a
// card that only goes away opens nothing, so a pane the person closed stays closed until there is something new.
async function openFreeformOnNewCards($: EngineInterface, b: DebriefBand | null): Promise<void> {
  const live = (b?.freeform ?? []).filter(isLiveCard)
  const cards = live.map(card => `${card.id}@${card.changedTurn}`)
  const seen = await read($, freeformSeenAtom)
  const firstNew = live.find((_, index) => !seen.includes(cards[index] ?? ''))
  await update($, freeformSeenAtom, () => cards)
  if (!firstNew) return
  const page = cardPagesOf((b?.freeform ?? []).filter(card => !card.isRetired)).findIndex(cardsOnPage => cardsOnPage.includes(firstNew))
  await update($, freeformPageAtom, () => Math.max(0, page))
  // Unasked, a narrow terminal holds the pane until it is wider; the chip reads open only once it shows.
  const opened = await $.ui.open({ id: FREEFORM_PANE, title: 'ATK Debrief' })
  if (opened.isPlaced) await update($, isFreeformOpenAtom, () => true)
}

// ↻: a rebuild now, or once the one running ends.
async function askRebuild($: EngineInterface): Promise<void> {
  const chat = await locateChat($)
  if (!chat) throw new Error('this chat has no transcript yet')
  scheduleRebuild($, chat)
}

// A press saves to state.json and redraws; a save that fails rejects, and the press's own catch says so.
async function saved($: EngineInterface, save: (chat: Chat) => Promise<void>): Promise<void> {
  const chat = await locateChat($)
  if (!chat) throw new Error('this chat has no transcript yet')
  await save(chat)
  await refresh($)
}

async function saveVerdict<S extends Section>($: EngineInterface, section: S, id: string, call: CallOf<S> | null): Promise<void> {
  await saved($, chat => setVerdict(ioOf($), chat, section, id, call))
}

async function saveAcknowledged($: EngineInterface, id: string, isAcknowledged: boolean): Promise<void> {
  await saved($, chat => setAcknowledged(ioOf($), chat, id, isAcknowledged))
}

async function saveProblemDismissed($: EngineInterface, id: string, isDismissed: boolean): Promise<void> {
  await saved($, chat => setProblemDismissed(ioOf($), chat, id, isDismissed))
}

// The settings as the pane shows them: the models Claude Code's own picker lists, read afresh each time.
async function shownOf($: EngineInterface, current: Settings) {
  const rows = await $.config.list()
  const offers = (Array.isArray(rows) ? rows : []).find(row => row.key === 'model')?.options ?? null
  return { ...current, choices: modelChoicesOf(current.model, offers) }
}

async function openSettings($: EngineInterface): Promise<void> {
  const shown = await shownOf($, await settingsOf(ioOf($)))
  await update($, settingsShownAtom, () => shown)
  await update($, settingsNotesAtom, () => ({ model: null, timeout: null }))
  const opened = await $.ui.open({ id: SETTINGS_PANE, title: 'ATK Debrief settings', focus: true })
  if (!opened.isPlaced) await $.ui.toast(`Settings pane not shown: ${opened.reason}`)
}

// A model from the list empties the Other model field, so it holds no id that is not in use. A pick that lands on the
// model in use is no change, so an Enter on the picker saves nothing.
async function pickModel($: EngineInterface, value: string): Promise<void> {
  await update($, modelIdRowAtom, row => row + 1)
  if (value === (await read($, settingsShownAtom))?.model) return
  await changeSettings($, { model: value })
}

// A change saves at once for every chat; one that cannot be used, or not saved, says why and changes nothing. Each
// field's note is its own, so a time limit saved while a model is checked leaves the "Checking" note.
async function changeSettings($: EngineInterface, change: { model?: string; timeoutSeconds?: string }): Promise<void> {
  const field = change.model !== undefined ? 'model' : 'timeout'
  const note = (text: string, isRefusal = false) => update($, settingsNotesAtom, notes => ({ ...notes, [field]: { text, isRefusal } }))
  const checked = change.model?.trim()
  if (checked && checked !== (await read($, settingsShownAtom))?.model) {
    await update($, modelCheckingAtom, () => checked)
    await note(`Checking ${checked}…`)
  }
  try {
    const { settings: stored, unchecked } = await saveSettings(ioOf($), change)
    const shown = await shownOf($, stored)
    await update($, settingsShownAtom, () => shown)
    const chat = await locateChat($)
    const isFixing = chat !== null && hasSettingsFix((await readState(ioOf($), chat).catch(() => ({}) as StoredState)).regenErrors ?? [])
    const caveat = unchecked ? ` It could not be checked now: ${unchecked}.` : ''
    const savedNote = field === 'model' ? `Saved: the next rebuild uses ${stored.model}.${caveat}` : `Saved: a rebuild stops after ${stored.timeoutSeconds} seconds.`
    await note(isFixing ? `${savedNote} This chat rebuilds now.` : savedNote)
    if (chat && isFixing) scheduleRebuild($, chat)
    await refresh($)
  } catch (error) {
    await note(error instanceof SettingsError ? error.message : `Not saved: ${(error as Error).message}`, true)
  } finally {
    if (checked) await update($, modelCheckingAtom, checking => (checking === checked ? null : checking))
  }
}

// Asked for by a press, the pane comes to the front; one the surface does not place says why. Opened to see the
// dismissed cards (no card is live), it shows them unfolded.
async function setFreeformOpen($: EngineInterface, isOpen: boolean, isForDismissed = false): Promise<void> {
  if (isOpen && isForDismissed) await update($, isFreeformDismissedOpenAtom, () => true)
  await update($, isFreeformOpenAtom, () => isOpen)
  if (!isOpen) return $.ui.close({ id: FREEFORM_PANE })
  const opened = await $.ui.open({ id: FREEFORM_PANE, title: 'ATK Debrief', focus: true })
  if (opened.isPlaced) return
  await update($, isFreeformOpenAtom, () => false)
  await $.ui.toast(`Freeform cards not shown: ${opened.reason}`)
}

let isPolling = false
let isCatchingUp = false

// Polling starts at the first band draw after the mod loads, so a session that never draws one (a headless run) never
// polls, records or rebuilds. The catch-up runs at the first draw of each session: the engine drops every plugin value
// at a /clear and keeps the module loaded, so the drawing after it catches up again. The catch-up and the first refresh
// wait for the drawing to end, as a drawing may not write state.
async function startPolling($: EngineInterface): Promise<void> {
  if (!isPolling) {
    isPolling = true
    // A poll that fails is tried again at the next; the band keeps what it last drew.
    $.clock.every(POLL_MS, () => void refresh($).catch(() => {}))
  }
  if (isCatchingUp || (await read($, hasDrawnAtom))) return
  isCatchingUp = true
  $.clock.after(0, () =>
    void catchUp($)
      .then(() => refresh($))
      .catch(() => {})
      .finally(() => {
        isCatchingUp = false
      }),
  )
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const result = await next(e)
    await $.command.register({ name: SETTINGS_COMMAND, description: 'ATK Debrief: the model and the time limit that rebuild the dashboard' })
    return result
  })

  on('command.run', { command: SETTINGS_COMMAND }, async $ => {
    await openSettings($)
    return {}
  }).catch(async $ => {
    await $.ui.toast('Settings not opened')
    return {}
  })

  // A turn opens at a message the user sends; a notice, a peer or a schedule speaks inside the turn it lands in.
  on('prompt.submit', async ($, e, next) => {
    const result = await next(e)
    const text = 'text' in result ? result.text : undefined
    if (typeof text !== 'string' || !isUsersOwn(e.origin)) return result
    // One typed over a running turn may still wait in the engine's queue when that turn ends.
    const prompt: PendingPrompt = { text, isMidTurn: e.turnId !== undefined }
    await update($, pendingPromptsAtom, list => [...pendingOf(list), prompt].slice(-MAX_PENDING))
    return result
  }).catch((_$, e, next) => next(e))

  // The main conversation's turn ended: its turns are recorded, then the board rebuilds in the background. A session
  // that never drew the band keeps its prompts for when it does.
  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    if (e.agentId !== undefined || !(await read($, hasDrawnAtom))) return result
    const chat = await locateChat($)
    if (!chat) return result
    if ((await recordPending($, chat)) && !e.isAborted) scheduleRebuild($, chat)
    return result
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    await startPolling($)
    const b = await read($, bandAtom)
    // A band an older build of the mod kept across a reload lacks parts this one draws; the next poll replaces it.
    if (b === null || e.props.hasSurvey || !Array.isArray(b.status.dismissedNotices)) return next(e)
    const isFolded = await read($, isBandFoldedAtom)
    const isFreeformOpen = await read($, isFreeformOpenAtom)
    const look = {
      openView: await read($, openViewAtom),
      isFolded,
      isAckedOpen: await read($, isAckedOpenAtom),
      isDoneOpen: await read($, isDoneOpenAtom),
      isResolvedOpen: await read($, isResolvedOpenAtom),
      isFreeformOpen,
      openNoticeIds: await read($, openNoticeIdsAtom),
    }
    const toastOf = (what: string) => (error: Error) => void $.ui.toast(`${what}: ${error.message}`)
    return drawBand($.ui.resolve(e), e.surface, b, look, {
      // A chip opens its view under the header and closes the one open there; on a folded band it unfolds it first.
      toggleView: view => {
        void update($, isBandFoldedAtom, () => false)
        void update($, openViewAtom, current => (isFolded || current !== view ? view : null))
      },
      toggleFold: () => void update($, isBandFoldedAtom, folded => !folded),
      rebuild: () => void askRebuild($).catch(toastOf('Dashboard rebuild not started')),
      toggleFreeform: () =>
        void setFreeformOpen($, !isFreeformOpen, b.freeform.filter(isLiveCard).length === 0).catch(toastOf('Freeform cards not shown')),
      reply: text => void quote($, text).catch(toastOf('Not quoted')),
      setAsk: (id, call) => void saveVerdict($, 'cta', id, call).catch(toastOf('Ask not updated')),
      setStep: (id, call) => void saveVerdict($, 'todo', id, call).catch(toastOf('Step not updated')),
      // An acknowledged heads-up joins the acknowledged group, opened to show it there, once the save is done.
      acknowledge: (id, isAcknowledged) =>
        isAcknowledged
          ? void saveAcknowledged($, id, true)
              .then(() => update($, isAckedOpenAtom, () => true))
              .catch(toastOf('Heads-up not acknowledged'))
          : void saveAcknowledged($, id, false).catch(toastOf('Heads-up not restored')),
      toggleAcked: () => void update($, isAckedOpenAtom, open => !open),
      toggleDone: () => void update($, isDoneOpenAtom, open => !open),
      toggleDetail: id => void update($, openNoticeIdsAtom, ids => (ids.includes(id) ? ids.filter(open => open !== id) : [...ids, id])),
      dismissProblem: (id, isDismissed) =>
        void saveProblemDismissed($, id, isDismissed).catch(toastOf(isDismissed ? 'Problem not dismissed' : 'Problem not restored')),
      toggleResolved: () => void update($, isResolvedOpenAtom, open => !open),
      openSettings: () => void openSettings($).catch(toastOf('Settings not opened')),
    })
  })
  // The person may close the cards pane with its own mark, and the chip then reads closed; every close comes here,
  // the mod's own included.
  on('ui.close', async ($, e, next) => {
    if (e.id === FREEFORM_PANE) await update($, isFreeformOpenAtom, () => false)
    return next(e)
  }).catch((_$, e, next) => next(e))

  on('ui.render', { component: 'Pane', requestId: SETTINGS_PANE }, async ($, e) => {
    const look = {
      shown: await read($, settingsShownAtom),
      notes: await read($, settingsNotesAtom),
      modelIdRow: await read($, modelIdRowAtom),
      checking: await read($, modelCheckingAtom),
    }
    return drawSettings($.ui.resolve(e), look, {
      pick: model => void pickModel($, model),
      change: change => void changeSettings($, change),
    })
  })

  on('ui.render', { component: 'Pane', requestId: FREEFORM_PANE }, async ($, e) => {
    const b = await read($, bandAtom)
    const look = { page: await read($, freeformPageAtom), isDismissedOpen: await read($, isFreeformDismissedOpenAtom), columns: e.props.bodyColumns }
    return drawCards($.ui.resolve(e), e.surface, b, look, {
      setCard: (id, isDismissed) =>
        void saveVerdict($, 'freeform', id, isDismissed ? 'dismissed' : null).catch(error => $.ui.toast(`Card not updated: ${error.message}`)),
      toPage: page => void update($, freeformPageAtom, () => page),
      toggleDismissed: () => void update($, isFreeformDismissedOpenAtom, open => !open),
    })
  })
}
