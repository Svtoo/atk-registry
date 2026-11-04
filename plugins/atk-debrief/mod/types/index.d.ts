export type DebriefAsk = { id: string; text: string; age: number; isDismissed: boolean }

export type DebriefLastTurn = { bullets: string[] }

export type DebriefHeadsup = {
  id: string
  sev: 'risk' | 'flag' | 'note'
  what: string
  why: string
  where: string
  raisedTurn: number | null
}

export type DebriefTodoStatus = 'open' | 'active' | 'done' | 'blocked'

export type DebriefTodo = {
  id: string
  text: string
  status: DebriefTodoStatus
  createdTurn: number | null
  doneTurn: number | null
  isChecked: boolean
  isDropped: boolean
}

export type DebriefLink = { id: string; label: string; url: string; kind: string }

export type DebriefPhase = 'planning' | 'building' | 'blocked' | 'review' | 'shipped'

export type DebriefFreshness = 'current' | 'updating' | 'behind' | 'failed'

export type DebriefNoticeStep = { text: string; command: string; href: string; hrefLabel: string }

export type DebriefNotice = {
  id: string
  severity: 'blocked' | 'degraded' | 'bug' | 'info'
  title: string
  what: string
  steps: DebriefNoticeStep[]
  detail: string
  diagnostics: { label: string; value: string }[]
  // Whether the person may set it aside: 'ack' with 🗑, 'none' for a problem that stays until it is fixed.
  dismiss: 'ack' | 'none'
  count: number
  ago: string
}

/** A problem as one line: one the person set aside, or one that resolved on its own. */
export type DebriefNoticeLine = { id: string; title: string; ago: string }

export type DebriefStatus = {
  freshness: DebriefFreshness
  /** The state in words, such as `current · 3m`: the status chip's hint, and its label on the terminal. */
  label: string
  /** How old the dashboard is, or how long its rebuild has run; null before its first build. */
  time: string | null
  stats: string
  notices: DebriefNotice[]
  dismissedNotices: DebriefNoticeLine[]
  resolvedNotices: DebriefNoticeLine[]
}

export type DebriefFreeformPart =
  | { kind: 'markdown'; text: string }
  | { kind: 'svg'; source: string; alt: string; width: number | null; height: number | null }

export type DebriefFreeform = {
  id: string
  title: string
  parts: DebriefFreeformPart[]
  changedTurn: number | null
  dismissedTurn: number | null
  isDismissed: boolean
  isRetired: boolean
  isOldFormat: boolean
}

export type DebriefBand = {
  hasDashboard: boolean
  phase: DebriefPhase | null
  turn: number
  lastTurn: DebriefLastTurn | null
  asks: DebriefAsk[]
  headsups: DebriefHeadsup[]
  ackedHeadsups: DebriefHeadsup[]
  todos: DebriefTodo[]
  links: DebriefLink[]
  freeform: DebriefFreeform[]
  status: DebriefStatus
}

/** The view a chip opens under the band's header. */
export type DebriefBandView = 'links' | 'headsups' | 'todos' | 'status'

/** The settings as the settings pane shows them, with the models its picker offers. */
export type DebriefSettingsShown = { model: string; timeoutSeconds: number; choices: string[] }

/** What the last change in a settings field came to, drawn under that field. */
export type DebriefSettingsNote = { text: string; isRefusal: boolean }

/** The note under each settings field, each kept apart so a change in one leaves the other's note. */
export type DebriefSettingsNotes = { model: DebriefSettingsNote | null; timeout: DebriefSettingsNote | null }

declare module 'claude-code' {
  interface PluginState {
    'atk-debrief': {
      band: DebriefBand | null
      openView: DebriefBandView | null
      isAckedOpen: boolean
      isDoneOpen: boolean
      openNoticeIds: string[]
      isResolvedOpen: boolean
      isFreeformOpen: boolean
      isFreeformDismissedOpen: boolean
      freeformSeen: string[]
      freeformPage: number
      pendingPrompts: { text: string; isMidTurn: boolean }[]
      lastPrompt: string | null
      hasDrawn: boolean
      isBandFolded: boolean
      settingsShown: DebriefSettingsShown | null
      settingsNotes: DebriefSettingsNotes
      modelIdRow: number
      modelChecking: string | null
    }
  }
}
