// The rebuild's status as the band shows it, and the problems a failed rebuild leaves, each worded for the person.
// Pure, as board.ts.

import type { DebriefFreshness, DebriefNotice, DebriefNoticeStep, DebriefStatus } from '../types'
import { withoutControls } from './board'

/** A failed rebuild as state.json keeps it; a repeat of an open one with the same code counts up instead of adding. */
export type RebuildError = {
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

type Copy = { severity: DebriefNotice['severity']; title: string; what: string; label: string; steps: DebriefNoticeStep[]; dismiss: DebriefNotice['dismiss'] }

/** The command that opens the settings pane; a step naming it opens the pane from the problem. */
export const SETTINGS_COMMAND = 'debrief-settings'

const step = (text: string, command = ''): DebriefNoticeStep => ({ text, command, href: '', hrefLabel: '' })
const settingsStep = (text: string) => step(text, `/${SETTINGS_COMMAND}`)

// Where a problem the person cannot end gets reported: the issues of the registry the plugin ships from.
const ISSUES_URL = 'https://github.com/Svtoo/atk-registry/issues'
const reportStep = (text: string): DebriefNoticeStep => ({ text, command: '', href: ISSUES_URL, hrefLabel: 'report it' })

const COPY: Record<string, Copy> = {
  'account.signed_out': {
    severity: 'blocked',
    title: 'Claude Code is signed out, so this dashboard has stopped updating.',
    what: 'The dashboard is written with your Claude Code sign in, and that sign in has lapsed. Nothing was lost; it catches up after your next reply once you sign in again.',
    label: 'signed out',
    steps: [step('Sign in again in Claude Code, with /login.'), step('Then keep working: the next reply rebuilds it.')],
    dismiss: 'none',
  },
  'account.usage_limit': {
    severity: 'blocked',
    title: 'Your Claude usage limit is reached, so rebuilds have paused.',
    what: 'The dashboard is written with your Claude subscription, which is refusing new work until its limit resets. Nothing is broken and nothing was lost.',
    label: 'usage limit',
    steps: [step('Wait for the limit to reset, then keep working: the next reply rebuilds it.')],
    dismiss: 'none',
  },
  'account.no_credit': {
    severity: 'blocked',
    title: 'The Claude account writing this dashboard has run out of credit.',
    what: 'The account signed in to Claude Code is billed by credit, and its balance is empty. Nothing on this computer is broken.',
    label: 'no credit',
    steps: [step('Add credit to the account, or sign in to another one with /login.'), step('Then keep working: the next reply rebuilds it.')],
    dismiss: 'none',
  },
  'account.refused': {
    severity: 'blocked',
    title: 'The account Claude Code calls the model with refused this rebuild.',
    what: "The account or credentials signed in to Claude Code cannot make this call; ▸ on this problem's row shows why. Nothing on this computer is broken, and the dashboard you have is unchanged.",
    label: 'account refused',
    steps: [step('Check the account with /status, or sign in to another one with /login.'), step('Then keep working: the next reply rebuilds it.')],
    dismiss: 'none',
  },
  'account.model_denied': {
    severity: 'blocked',
    title: 'Your Claude account cannot use the model this dashboard is set to.',
    what: 'Every rebuild names a model, and the one set here is refused. The dashboard you have is unchanged.',
    label: 'model unavailable',
    steps: [settingsStep('Pick a model your account can use in the settings.')],
    dismiss: 'none',
  },
  'rebuild.timeout': {
    severity: 'degraded',
    title: 'This rebuild was stopped for taking too long.',
    what: 'It ran past the time limit and was stopped. It tries again after your next reply; if it keeps happening, raise the limit.',
    label: 'took too long',
    steps: [settingsStep('Raise the time limit in the settings.')],
    dismiss: 'ack',
  },
  'rebuild.bad_output': {
    severity: 'bug',
    title: 'The rebuild came back in a form the dashboard could not use.',
    what: 'The answer did not match the shape the dashboard expects, and neither did the corrected answer the model was asked for, so both were thrown away rather than shown half-broken. The dashboard you have is unchanged, and it tries again after your next reply.',
    label: 'bad output',
    steps: [step('Nothing to do: it tries again after your next reply.'), reportStep('If this chat keeps doing it,')],
    dismiss: 'ack',
  },
  'rebuild.refused': {
    severity: 'degraded',
    title: 'The request this rebuild sent was refused.',
    what: "The request did not pass the checks of Claude Code or the model service, for example a model that cannot write a reply this long, or a request too long for the model. The dashboard you have is unchanged. It tries again after your next reply, and the same request may be refused again.",
    label: 'request refused',
    steps: [settingsStep('If it keeps happening, pick another model in the settings.'), reportStep('If that does not help,')],
    dismiss: 'ack',
  },
  'rebuild.failed': {
    severity: 'degraded',
    title: 'A rebuild of this dashboard did not finish.',
    what: "The reason is under ▸ on this problem's row. Nothing was lost: the dashboard you have is unchanged, and it tries again after your next reply.",
    label: 'did not finish',
    steps: [step("Rebuild it now with ↻ at the end of the band's first line, or wait for your next reply."), reportStep('If it keeps happening,')],
    dismiss: 'ack',
  },
}

const FALLBACK_CODE = 'rebuild.failed'
const copyOf = (code: string) => COPY[code] ?? (COPY[FALLBACK_CODE] as Copy)

// The API errors that say the account or its credentials may not make the call at all.
const ACCOUNT_REFUSALS = new Set(['oauth_org_not_allowed', 'account_on_hold', 'verification_required', 'cloud_credential_error'])

/** The problem for an API error of the rebuild's model call, by the kind Claude Code names it. */
export function codeOfApiError(kind: string): string {
  if (kind === 'authentication_failed') return 'account.signed_out'
  if (kind === 'billing_error') return 'account.no_credit'
  if (kind === 'rate_limit') return 'account.usage_limit'
  if (kind === 'model_not_found') return 'account.model_denied'
  if (ACCOUNT_REFUSALS.has(kind)) return 'account.refused'
  if (kind === 'invalid_request') return 'rebuild.refused'
  return FALLBACK_CODE
}

/** An API error that may clear on its own within seconds, worth one more try; a rate limit that stays is a usage limit. */
export const isPassing = (kind: string) => kind === 'overloaded' || kind === 'server_error' || kind === 'rate_limit'

const isOpen = (error: RebuildError) => error.ackedAt === null && error.resolvedAt === null

// The problems a change in the settings can end: the time limit, or the model asked for.
const SETTINGS_FIXES = new Set(['rebuild.timeout', 'account.model_denied', 'rebuild.refused'])

/** Whether one of the chat's open problems is one a change in the settings can end. */
export const hasSettingsFix = (errors: RebuildError[]) => errors.some(error => isOpen(error) && SETTINGS_FIXES.has(error.code))

const MAX_ERRORS = 50
const MAX_MESSAGE = 4096

/** The chat's errors with this one recorded: a repeat of an open error with its code counts up, else it is added. */
export function withError(errors: RebuildError[], error: { code: string; kind: string; message: string }, nowSeconds: number, idOf: () => string): RebuildError[] {
  const message = error.message.length > MAX_MESSAGE ? `${error.message.slice(0, MAX_MESSAGE)}\n…[cut]` : error.message
  const repeat = [...errors].reverse().find(e => e.code === error.code && isOpen(e))
  if (repeat) return errors.map(e => (e === repeat ? { ...e, count: e.count + 1, lastAt: nowSeconds, kind: error.kind, message } : e))
  const added: RebuildError = { id: idOf(), at: nowSeconds, lastAt: nowSeconds, count: 1, code: error.code, kind: error.kind, message, ackedAt: null, resolvedAt: null }
  return [...errors, added].slice(-MAX_ERRORS)
}

/** The chat's errors once a rebuild succeeded: every open one is resolved. */
/** The errors with every one not resolved yet resolved now, by a rebuild that succeeded; one dismissed resolves too. */
export const resolvedErrors = (errors: RebuildError[], nowSeconds: number) => errors.map(e => (e.resolvedAt === null ? { ...e, resolvedAt: nowSeconds } : e))

/** Seconds as the band shows an age: 45s, 3m, 2h, 4d. */
function ageOf(seconds: number): string {
  if (seconds < 60) return `${Math.max(0, Math.floor(seconds))}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`
  return `${Math.floor(seconds / 86400)}d`
}

function noticeOf(error: RebuildError, nowSeconds: number): DebriefNotice {
  const copy = copyOf(error.code)
  return {
    id: error.id,
    severity: copy.severity,
    title: copy.title,
    what: copy.what,
    steps: copy.steps,
    detail: withoutControls(error.message),
    diagnostics: [
      { label: 'Failure', value: error.code },
      { label: 'Kind', value: error.kind },
    ],
    dismiss: copy.dismiss,
    count: error.count,
    ago: `${ageOf(nowSeconds - error.lastAt)} ago`,
  }
}

// The problems that resolved on their own that the status view lists, newest first.
const RESOLVED_SHOWN = 5

/**
 * What the chat's rebuilds took, summed over the ones that saved a board, from what each model call reports: its
 * tokens and how long it ran. Input counts every prompt token; `cachedInputTokens` is the part read from the prompt
 * cache over the `cachedRebuilds` that reported it, fewer than `rebuilds` in totals begun before it was kept, and
 * absent from totals older than that. `models` names the model settings the rebuilds asked for.
 */
export type RebuildStats = {
  rebuilds: number
  inputTokens: number
  cachedInputTokens: number
  cachedRebuilds: number
  outputTokens: number
  wallMs: number
  models: string[]
}

type StatusFacts = {
  // Since when a rebuild of this chat runs in this session, else null.
  runningSince: number | null
  // When the last rebuild succeeded, in seconds, and how many recorded turns the dashboard does not hold yet.
  rebuiltAt: number | null
  unbuiltTurns: number
  errors: RebuildError[]
  // What the chat's saved rebuilds took, summed; absent before the first. Totals older rebuilds lack count as 0.
  stats?: Omit<RebuildStats, 'cachedInputTokens' | 'cachedRebuilds'> & Partial<RebuildStats>
}

// A count of tokens as the band shows it: 950, 32.6k, 3.2M. Thousands rounded to a tenth first, so 999,999 reads 1M.
function tokensOf(n: number): string {
  const thousands = Math.round(n / 100) / 10
  if (thousands >= 1000) return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`
  return n >= 1000 ? `${thousands.toFixed(1).replace(/\.0$/, '')}k` : String(n)
}

/**
 * The chat's rebuilds in one line, only from what the model calls reported: how many, their total tokens in (with the
 * cached part, when every rebuild reported it) and out, their average time, and the models asked for; empty before
 * the first.
 */
export function statsOf(stats: StatusFacts['stats']): string {
  if (!stats?.rebuilds) return ''
  const n = stats.rebuilds
  const cached = stats.cachedRebuilds === n ? `, ${tokensOf(stats.cachedInputTokens ?? 0)} cached` : ''
  return [
    `${n} rebuild${n === 1 ? '' : 's'}`,
    `${tokensOf(stats.inputTokens)} tokens in${cached}, ${tokensOf(stats.outputTokens)} out`,
    `avg ${(stats.wallMs / n / 1000).toFixed(1)}s`,
    ...(stats.models.length > 0 ? [stats.models.join(', ')] : []),
  ].join(' · ')
}

/** The status chip and its problems, from what this session and state.json know. */
export function statusOf(facts: StatusFacts, nowSeconds: number): DebriefStatus {
  const open = facts.errors.filter(isOpen)
  const freshness: DebriefFreshness =
    facts.runningSince !== null ? 'updating' : open.length > 0 ? 'failed' : facts.rebuiltAt !== null && facts.unbuiltTurns > 0 ? 'behind' : 'current'
  const newest = open.at(-1)
  const label =
    freshness === 'updating'
      ? `updating · ${ageOf(nowSeconds - (facts.runningSince ?? nowSeconds))}`
      : freshness === 'failed' && newest
        ? `${open.length > 1 ? `${open.length} × ` : ''}${copyOf(newest.code).label}`
        : freshness === 'behind'
          ? `behind ${facts.unbuiltTurns} turn${facts.unbuiltTurns === 1 ? '' : 's'}`
          : facts.rebuiltAt === null
            ? 'current'
            : `current · ${ageOf(nowSeconds - facts.rebuiltAt)}`
  const time =
    freshness === 'updating' ? ageOf(nowSeconds - (facts.runningSince ?? nowSeconds)) : facts.rebuiltAt === null ? null : ageOf(nowSeconds - facts.rebuiltAt)
  return {
    freshness,
    label,
    time,
    stats: statsOf(facts.stats),
    notices: [...open].reverse().map(error => noticeOf(error, nowSeconds)),
    // Set aside by the person until a rebuild succeeds, each with ↶.
    dismissedNotices: facts.errors
      .filter(error => error.ackedAt !== null && error.resolvedAt === null)
      .map(error => ({ id: error.id, title: copyOf(error.code).title, ago: `${ageOf(nowSeconds - error.lastAt)} ago` })),
    resolvedNotices: facts.errors
      .filter(error => error.resolvedAt !== null)
      .slice(-RESOLVED_SHOWN)
      .reverse()
      .map(error => ({ id: error.id, title: copyOf(error.code).title, ago: `${ageOf(nowSeconds - (error.resolvedAt ?? nowSeconds))} ago` })),
  }
}
