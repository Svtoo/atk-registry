// The world every mod test runs in, its fixtures, and the helpers that mount and read what the mod draws.
import { mock } from 'claude-code/testing'

export const HOME = '/Users/you'
export const PROJECT = '-Users-you-work'
export const SESSION = 'aaaaaaaa-1111-2222-3333-444444444444'
export const CHAT_DIR = `${HOME}/.claude/projects/${PROJECT}/${SESSION}`

export const OLDEST_ASK_COLOR = '#ef4444'
export const NEWEST_ASK_COLOR = '#6366f1'
export const RISK_COLOR = '#ef4444'
export const FLAG_COLOR = '#f59e0b'
// A bar cell is 10px wide, with a 2px gap to the next.
export const barWidthOf = (cells: number) => cells * 12 - 2
export const GREEN = '#10b981'
export const DONE_COLOR = GREEN
export const ACTIVE_COLOR = '#6366f1'
export const OPEN_COLOR = '#9ca3af'
export const BLOCKED_COLOR = '#ef4444'
// Text names the theme key for its colour, so it follows a light or dark theme; a drawing keeps the hex.
export const RISK_TEXT = 'error'
export const FLAG_TEXT = 'warning'
export const GREEN_TEXT = 'success'
export const ACTIVE_TEXT = 'permission'
export const OPEN_TEXT = 'inactive'
export const THEME_TEXTS = [RISK_TEXT, FLAG_TEXT, GREEN_TEXT, ACTIVE_TEXT, OPEN_TEXT]

export const NOW_S = 1_800_000_000
// The dashboard was written three minutes ago, after the last turn ended.
export const WRITTEN_AGO_S = 180

export const BAND = { hasSurvey: false, isWorking: false, maxRows: 24, bodyColumns: 100, scroll: { offset: 0, bodyRows: 24 }, view: {} }

export type Model = {
  phase: string
  turn: number
  turn_base: number
  last_turn: { bullets: string[]; turn: number }
  cta: { id: string; text: string; created_turn: number }[]
  headsup?: Headsup[]
  todo?: Todo[]
  links?: Link[]
  freeform?: Freeform[]
}

export type Freeform = { id: string; body: string; hash?: string; changed_turn: number; dismissed_turn: number }

export type Headsup = { id: string; sev: 'risk' | 'flag'; what: string; why: string; where: string; created_turn: number }

// A failed rebuild as state.json keeps it.
export type StoredError = {
  id: string
  at: number
  lastAt: number
  count: number
  code: string
  kind: string
  message: string
  ackedAt: number | null
  resolvedAt: number | null
}

export type Link = { id: string; label: string; url: string; kind: string }

export type Todo = { id: string; text: string; status: 'open' | 'active' | 'done' | 'blocked'; created_turn: number; done_turn: number }

export type Sent = { method: string; url: string; body?: string }

export type Turns = { count: number; endedAt: number; prompts: string[] }

export type Unanswered = { isAnswered: false; reason: string; error?: string; status?: number | null }
export type Answer = string | Unanswered | (() => Promise<string | Unanswered>)

export type World = {
  clock: ReturnType<typeof mock.clock>
  opened: string[]
  closed: string[]
  sent: Sent[]
  fills: string[]
  // What the prompt box holds before a fill, and what the next fill comes to.
  draft: string
  fillResult: { isFilled: boolean; refusal?: 'dialog' | 'no_composer' }
  toasts: string[]
  reads: string[]
  state: {
    model: Model | null
    verdicts: Record<string, { verdict: string }>
    acks: Record<string, { ackedAt: number }>
    mtimeMs: number
    rebuiltAt: number | null
    turns: Turns | null
    regenErrors: StoredError[]
    stats?: { rebuilds: number; inputTokens: number; cachedInputTokens: number; cachedRebuilds: number; outputTokens: number; wallMs: number; models: string[] }
  }
  // Files the mod wrote beside the chat, other than state.json, by path.
  files: Record<string, string>
  placement: { isPlaced: true } | { isPlaced: false; reason: string }
  // The rebuild's model calls, and what the model answers next, in order.
  requests: { model: string; system: string; prompt: string; maxTokens: number; timeoutMs: number }[]
  answers: Answer[]
  messages: { role: 'user' | 'assistant'; text: string; toolUses: unknown[]; toolResults?: unknown[] }[]
  // Why a write of state.json fails, as the OS says it, or null when it succeeds.
  writeError: string | null
  // The slash commands the mod registered.
  commands: string[]
  // The rows of Claude Code's own config menu, as $.config.list gives them.
  configRows: { key: string; label: string; kind: string; value: string; options?: string[] }[]
}

export const MODEL: Model = {
  phase: 'review',
  turn: 21,
  turn_base: 0,
  last_turn: {
    bullets: ['Filed the bug as <code>claude-code#100633</code>.', 'Fixed the PRESS_LOG error.', 'Neither press is tested yet.'],
    turn: 21,
  },
  cta: [
    { id: 'c2', text: 'Run the free review on the 3 over-budget mental models?', created_turn: 3 },
    { id: 'c19', text: 'Press the button in manual mode, then in auto mode.', created_turn: 21 },
  ],
}

export const [OLD_ASK, NEW_ASK] = MODEL.cta as [Model['cta'][number], Model['cta'][number]]
// The last turn as the band draws it: the first bullet's <code> becomes Markdown.
export const BULLETS = ['Filed the bug as `claude-code#100633`.', ...MODEL.last_turn.bullets.slice(1)]
export const ASK_TEXTS = MODEL.cta.map(ask => ask.text)

export const SIGNED_OUT_ERROR: StoredError = {
  id: 'err-1800000000-0000000a',
  at: NOW_S - 120,
  lastAt: NOW_S - 120,
  count: 1,
  code: 'account.signed_out',
  kind: 'authentication_failed',
  message: 'the model call failed: authentication_failed (HTTP 401)',
  ackedAt: null,
  resolvedAt: null,
}
export const SIGNED_OUT_TITLE = 'Claude Code is signed out, so this dashboard has stopped updating.'
export const SIGNED_OUT_WHAT =
  'The dashboard is written with your Claude Code sign in, and that sign in has lapsed. Nothing was lost; it catches up after your next reply once you sign in again.'
export const SIGNED_OUT_STEPS = ['Sign in again in Claude Code, with /login.', 'Then keep working: the next reply rebuilds it.']

export const TIMEOUT_ERROR: StoredError = {
  id: 'err-1799999400-0000000b',
  at: NOW_S - 900,
  lastAt: NOW_S - 600,
  count: 2,
  code: 'rebuild.timeout',
  kind: 'timeout',
  message: 'the model call ran past 180s and was stopped',
  ackedAt: null,
  resolvedAt: null,
}
export const TIMEOUT_TITLE = 'This rebuild was stopped for taking too long.'
// The limit it ran past is in its detail; the settings may hold another by now.
export const TIMEOUT_WHAT = 'It ran past the time limit and was stopped. It tries again after your next reply; if it keeps happening, raise the limit.'
export const TIMEOUT_STEP = 'Raise the time limit in the settings.'

// Oldest first, as state.json keeps them; the band lists the newest first.
export const ERRORS = [TIMEOUT_ERROR, SIGNED_OUT_ERROR]
export const SHOWN_ERRORS = [SIGNED_OUT_ERROR, TIMEOUT_ERROR]

export const RESOLVED_ERROR: StoredError = { ...TIMEOUT_ERROR, id: 'err-1799990000-0000000c', count: 1, at: NOW_S - 7200, lastAt: NOW_S - 7200, resolvedAt: NOW_S - 3600 }

export const OLD_RISK: Headsup = {
  id: 'h1',
  sev: 'risk',
  what: 'The old copies may not be in the Trash.',
  why: 'A later check of the Trash was denied.',
  where: '~/.claude/skills/atk-debrief',
  created_turn: 3,
}

export const FLAG: Headsup = {
  id: 'h2',
  sev: 'flag',
  what: 'The band polls the server in <b>every</b> session.',
  why: 'Headless runs send a request every two seconds.',
  where: 'hooks/register.tsx',
  created_turn: 20,
}

export const NEW_FLAG: Headsup = {
  id: 'h3',
  sev: 'flag',
  what: 'The registry copy is behind the working copy.',
  why: 'A release would ship the old band.',
  where: '',
  created_turn: 21,
}

// Oldest first, as the dashboard stores them.
export const HEADSUPS = [OLD_RISK, FLAG, NEW_FLAG]

export const DONE_TODO: Todo = { id: 't1', text: 'Read how the web page draws the to-do.', status: 'done', created_turn: 2, done_turn: 4 }
export const ACTIVE_TODO: Todo = { id: 't3', text: 'Draw the bar with <code>Svg</code> cells.', status: 'active', created_turn: 5, done_turn: 0 }
export const BLOCKED_TODO: Todo = { id: 't5', text: 'Release to the registry.', status: 'blocked', created_turn: 21, done_turn: 0 }
export const OPEN_TODO: Todo = { id: 't4', text: 'Open the section from the line.', status: 'open', created_turn: 20, done_turn: 0 }
export const UNSTAMPED_DONE_TODO: Todo = { id: 't2', text: 'Count the steps of real chats.', status: 'done', created_turn: 2, done_turn: 0 }
export const UNSTAMPED_OPEN_TODO: Todo = { id: 't6', text: 'Write the README part.', status: 'open', created_turn: 0, done_turn: 0 }

export const ISSUE_LINK: Link = { id: 'l1', label: 'ENG-6753 (opener split)', url: 'https://linear.app/o/issue/ENG-6753', kind: 'issue' }
export const PR_LINK: Link = { id: 'l2', label: 'PR #7: fixes &amp; tests', url: 'https://github.com/o/r/pull/7', kind: 'pr' }
export const NO_ADDRESS_LINK: Link = { id: 'l3', label: 'main', url: '', kind: 'branch' }
export const NOTEBOOK_LINK: Link = { id: 'l4', label: 'Notebook [local]', url: 'http://localhost:2720/', kind: 'notebook' }
export const LINKS = [ISSUE_LINK, PR_LINK, NO_ADDRESS_LINK, NOTEBOOK_LINK]
// A Link on the desktop opens https only; a Markdown link opens http and file addresses too.
export const ISSUE_MARKDOWN = `[${ISSUE_LINK.label}](${ISSUE_LINK.url})`
export const PR_MARKDOWN = `[PR #7: fixes & tests](${PR_LINK.url})`
export const NOTEBOOK_MARKDOWN = `[Notebook \\[local\\]](${NOTEBOOK_LINK.url})`

export const steps = (status: Todo['status'], count: number): Todo[] => Array.from({ length: count }, (_, index) => ({ ...OPEN_TODO, id: `${status}-${index}`, status }))

// The plan in the order the dashboard stores it.
export const TODOS = [DONE_TODO, ACTIVE_TODO, BLOCKED_TODO, OPEN_TODO, UNSTAMPED_DONE_TODO, UNSTAMPED_OPEN_TODO]
export const plainStepOf = (todo: Todo) => todo.text.replace(/<\/?code>/g, '')
export const markdownStepOf = (todo: Todo) => todo.text.replace(/<\/?code>/g, '`')

// What an element shows, as FoundElement.text reads it, less what is hidden: a hint shows only under the pointer.
function shownTextOf(node: any): string {
  if (typeof node === 'string') return node
  if (!node || typeof node !== 'object' || node.props?.display === 'none') return ''
  if (node.type === 'Markdown') return node.props.text ?? ''
  if (node.type === 'Button') return node.props.label ?? ''
  return (node.children ?? []).map(shownTextOf).join('')
}

/** The text the element with this key shows, its hidden hints left out. */
export async function shownText(ui: any, key: string): Promise<string | undefined> {
  const find = (node: any): any =>
    node && typeof node === 'object' ? ((node.props?.key ?? node.key) === key ? node : (node.children ?? []).map(find).find(Boolean)) : undefined
  const found = find(await ui.drawn())
  return found ? shownTextOf(found) : undefined
}

export const rowsKeyed = (prefix: string) => async (ui: any) =>
  (await ui.findAll({ type: 'Box' })).map((box: { key?: string }) => box.key).filter((key?: string) => key?.startsWith(prefix))
export const headsupRows = rowsKeyed('headsup-')
export const ackedRows = rowsKeyed('acked-')
export const todoRows = rowsKeyed('todo-')
export const doneRows = rowsKeyed('done-')
export const linkRows = rowsKeyed('link-')
export const dismissedLinkRows = rowsKeyed('dismissed-link-')
export const noticeRows = rowsKeyed('notice-err')

export const EMPTY_ANSWER = '<update>{"ops":[]}</update>'

// The models Claude Code 2.1.308's own picker listed, read from its config row.
export const CLAUDE_CODE_MODELS = ['default', 'sonnet', 'opus', 'haiku', 'fable', 'best', 'sonnet[1m]', 'opus[1m]', 'fable[1m]', 'opusplan']

export const stateJsonOf = (w: World) =>
  JSON.stringify({
    version: 1,
    model: w.state.model,
    verdicts: w.state.verdicts,
    acks: w.state.acks,
    regenErrors: w.state.regenErrors,
    ...(w.state.rebuiltAt === null ? {} : { rebuiltAt: w.state.rebuiltAt }),
    ...(w.state.turns === null ? {} : { turns: w.state.turns }),
    ...(w.state.stats ? { stats: w.state.stats } : {}),
  })

// `settings` are what the settings pane saved in the mod's store before the test; none when left out.
export function world(on: any, model: Model | null = MODEL, settings?: { model: string; timeoutSeconds: number }, env: Record<string, string> = {}): World {
  const w: World = {
    clock: mock.clock(on, { now: NOW_S * 1000 }),
    opened: [],
    closed: [],
    sent: [],
    fills: [],
    draft: '',
    fillResult: { isFilled: true },
    toasts: [],
    reads: [],
    state: {
      model,
      verdicts: {},
      acks: {},
      mtimeMs: 1_000,
      rebuiltAt: model ? NOW_S - WRITTEN_AGO_S : null,
      turns: model ? { count: model.turn, endedAt: NOW_S - WRITTEN_AGO_S - 10, prompts: [] } : null,
      regenErrors: [],
    },
    files: {},
    placement: { isPlaced: true },
    requests: [],
    answers: [],
    messages: [],
    writeError: null,
    commands: [],
    configRows: [{ key: 'model', label: 'Model', kind: 'choice', value: 'Default (recommended)', options: CLAUDE_CODE_MODELS }],
  }
  const hasState = () => w.state.model !== null || w.state.turns !== null || w.state.regenErrors.length > 0
  mock.env(on, { HOME, ...env })
  mock.store(on, settings ? { settings } : {})
  on('session.start', (_$: any, e: any) => ({ cwd: e.cwd }))
  on('config.list', () => ({ value: w.configRows }))
  on('command.register', (_$: any, e: any) => {
    w.commands.push(e.name)
    return { value: { command: e.name } }
  })
  on('session.id', () => ({ value: SESSION }))
  on('session.messages', () => ({ value: w.messages }))
  // The engine beneath: a prompt enters as sent, a turn ends with its answer.
  on('prompt.submit', (_$: any, e: any) => ({ text: e.text }))
  on('turn.complete', (_$: any, e: any) => ({ text: e.answer }))
  on('turn.start', (_$: any, e: any) => ({ turnId: e.turnId }))
  on('fs.list', (_$: any, e: any) => {
    // The project folder holds this chat and any chat whose files the test laid there.
    if (e.path === `${HOME}/.claude/projects/${PROJECT}`) {
      const names = new Set([SESSION, ...Object.keys(w.files).map(path => path.slice(e.path.length + 1).split('/')[0] ?? '')])
      return { value: [...names].map(name => ({ name, kind: 'dir', size: 0, mtimeMs: 0, isLink: false })) }
    }
    if (e.path !== `${HOME}/.claude/projects`) throw new Error(`ENOENT ${e.path}`)
    return { value: [{ name: 'other', kind: 'dir', size: 0, mtimeMs: 0, isLink: false }, { name: PROJECT, kind: 'dir', size: 0, mtimeMs: 0, isLink: false }] }
  })
  on('fs.exists', (_$: any, e: any) => ({
    value: e.path === `${HOME}/.claude/projects/${PROJECT}/${SESSION}.jsonl` || (e.path === `${CHAT_DIR}/state.json` && hasState()) || e.path in w.files,
  }))
  on('fs.stat', (_$: any, e: any) => {
    if (e.path === `${CHAT_DIR}/state.json` && hasState()) return { value: { kind: 'file', size: stateJsonOf(w).length, mtimeMs: w.state.mtimeMs, isLink: false, resolve: false } }
    throw new Error(`ENOENT ${e.path}`)
  })
  on('fs.read', (_$: any, e: any) => {
    w.reads.push(e.path)
    if (e.path.endsWith('/SYSTEM.md')) return { value: 'You keep the dashboard.\n' }
    if (e.path === `${CHAT_DIR}/state.json` && hasState()) return { value: stateJsonOf(w) }
    if (e.path in w.files) return { value: w.files[e.path] }
    throw new Error(`ENOENT ${e.path}`)
  })
  on('fs.write', (_$: any, e: any) => {
    if (e.path !== `${CHAT_DIR}/state.json`) {
      w.files[e.path] = e.text
      return { value: undefined }
    }
    if (w.writeError !== null) return { deny: w.writeError }
    const saved = JSON.parse(e.text)
    w.state = {
      ...w.state,
      model: saved.model ?? null,
      verdicts: saved.verdicts ?? {},
      acks: saved.acks ?? {},
      regenErrors: saved.regenErrors ?? [],
      rebuiltAt: saved.rebuiltAt ?? null,
      turns: saved.turns ?? null,
      ...(saved.stats ? { stats: saved.stats } : {}),
      mtimeMs: w.state.mtimeMs + 1,
    }
    return { value: undefined }
  })
  on('model.complete', async (_$: any, e: any) => {
    w.requests.push(e)
    const next = w.answers.shift() ?? EMPTY_ANSWER
    const answer = typeof next === 'function' ? await next() : next
    // Each answer reads 1 token from the prompt cache beside its 1 fresh input token, and writes 1 token.
    const usage = { input_tokens: 1, cache_read_input_tokens: 1, cache_creation_input_tokens: 0, output_tokens: 1 }
    if (typeof answer === 'string') return { value: { isAnswered: true, text: answer, usage } }
    return { value: { usage: { input_tokens: 1, output_tokens: 0 }, ...answer } }
  })
  // Nothing in the band reaches a server any more; a request here is a bug, recorded so a test can say so.
  on('http.fetch', (_$: any, e: any) => {
    w.sent.push({ method: e.init?.method ?? 'GET', url: e.url, ...(e.init?.body ? { body: e.init.body } : {}) })
    return { value: { status: 404, ok: false, headers: {}, text: '' } }
  })
  on('ui.render', { component: 'AbovePrompt' }, ($: any, e: any) => {
    const { Box } = $.ui.resolve(e)
    return <Box key="engine-band" />
  })
  on('ui.open', (_$: any, e: any) => {
    w.opened.push(`${e.id}: ${e.title}${e.focus ? ' (focus)' : ''}`)
    return { value: w.placement }
  })
  on('ui.close', (_$: any, e: any) => {
    w.closed.push(e.id)
    return { value: undefined }
  })
  on('prompt.read', () => ({ value: { text: w.draft, cursor: w.draft.length } }))
  on('prompt.fill', (_$: any, e: any) => {
    if (w.fillResult.isFilled) w.fills.push(e.text)
    return { ...w.fillResult, text: w.draft + e.text }
  })
  on('ui.toast', (_$: any, e: any) => {
    w.toasts.push(String(e.text))
    return { value: undefined }
  })
  return w
}

// The desktop app hosts its chats through the SDK: they start with no surface and not interactive.
export const START = {
  desktop: { cwd: '/w', surface: null, isInteractive: false },
  terminal: { cwd: '/w', surface: 'terminal', isInteractive: true },
}

/** The status chip: its label, then the hint that names its state while the pointer is over it (none on the terminal). */
export async function statusChipOf(ui: any): Promise<[string | undefined, string | undefined]> {
  const textOf = (tree: any): string => (typeof tree === 'string' ? tree : (tree?.children ?? []).map(textOf).join(''))
  const hint = ((await ui.find({ key: 'hint-status' }))?.children ?? []).find((child: any) => child?.props?.position === 'absolute')
  return [(await ui.find({ key: 'status' }))?.props.label, hint && textOf(hint).trim()]
}

export async function mountBand($: any, w: World, surface: 'desktop' | 'terminal' = 'desktop') {
  await $.session.start(START[surface])
  await w.clock.settle()
  const ui = await $.ui.mount({ plugin: 'atk-debrief', surface, component: 'AbovePrompt', props: BAND })
  await w.clock.settle()
  return ui
}

export const markdownTexts = async (ui: any) => (await ui.findAll({ type: 'Markdown' })).map((markdown: { props: { text: string } }) => markdown.props.text)
export const circleFillOf = (svg: string) => svg.match(/<circle[^>]*fill="([^"]+)"/)?.[1]
// A filled cell gives its fill; an open cell is an outline and gives its stroke.
export const cellColorsOf = (svg: string) => [...svg.matchAll(/<rect[^>]*?(?:fill|stroke)="(#\w+)"/g)].map(match => match[1])
export const todoMarkersOf = async (ui: any) =>
  (await ui.findAll({ type: 'Svg' }))
    .filter((svg: { props: { alt: string } }) => !svg.props.alt.startsWith('ask ') && !svg.props.alt.endsWith(' done'))
    .map((svg: { props: { alt: string; source: string } }) => [svg.props.alt, cellColorsOf(svg.props.source)])
export const todoBarOf = async (ui: any) =>
  (await ui.findAll({ type: 'Svg' })).find((svg: { props: { alt: string } }) => svg.props.alt.endsWith(' done')) as { props: { alt: string; source: string; width: number } } | undefined

export const FREEFORM_PANE = 'debrief-freeform'
export const PANE_PROPS = { title: 'ATK Debrief', isFocused: false, bodyColumns: 100, placement: 'dock', scroll: { offset: 0, bodyRows: 40 }, view: {} }
export const DIAGRAM = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 60" width="200" height="60" aria-label="agent to server"><rect x="4" y="4" width="80" height="40" rx="6" fill="none" stroke="var(--accent)"/></svg>'
export const DESIGN_TABLE = '| Part | Owner |\n| --- | --- |\n| band | mod |'
export const DESIGN_CARD: Freeform = { id: 'f1', body: `## Design of the band\n\nThe **band** reads the state.\n\n${DIAGRAM}\n\n${DESIGN_TABLE}`, changed_turn: 18, dismissed_turn: 0 }
export const HTML_CARD: Freeform = { id: 'f2', body: '<section class="card free-form"><h2>Old card</h2><p>old</p></section>', changed_turn: 10, dismissed_turn: 0 }
export const RETIRED_CARD: Freeform = { id: 'f3', body: '## A retired sketch\n\nan old sketch', changed_turn: 5, dismissed_turn: 9 }
export const CARDS_MODEL: Model = { ...MODEL, freeform: [DESIGN_CARD, HTML_CARD, RETIRED_CARD] }

export async function mountPane($: any, w: World, surface: 'desktop' | 'terminal' = 'desktop') {
  const band = await mountBand($, w, surface)
  const pane = await $.ui.mount({ plugin: 'atk-debrief', surface, component: 'Pane', requestId: FREEFORM_PANE, props: PANE_PROPS })
  await w.clock.settle()
  return { band, pane }
}

export const unmountAll = async (...uis: any[]) => {
  for (const ui of uis) await ui.unmount()
}

export const SETTINGS_PANE = 'debrief-settings'
