// The two panes beside the chat: the Freeform cards and the settings. Pure drawing, as band.tsx is: register.tsx reads
// the atoms and hands in what each press does.
import type { ElementTable, RenderElement, RenderSurface } from 'claude-code'

import type { DebriefBand, DebriefFreeform, DebriefFreeformPart, DebriefSettingsNotes, DebriefSettingsShown } from '../types'
import { freeformAgeOf } from './band-model'
import { COLORS, textColorOf } from './colors'
import { GLYPHS, kitOf } from './kit'
import { SETTINGS_COMMAND } from './status'

// One drawing holds 100,000 characters of Markdown; cards past it go on further pages.
const FREEFORM_MARKDOWN_BUDGET = 90_000

const markdownSizeOf = (card: DebriefFreeform) => card.parts.reduce((sum, part) => sum + (part.kind === 'markdown' ? part.text.length : 0), 0)

/** The cards in pages, each as many as one drawing's Markdown holds, in order; a card alone on its page is always drawn. */
export function cardPagesOf(cards: DebriefFreeform[]): DebriefFreeform[][] {
  const pages: DebriefFreeform[][] = []
  let used = 0
  for (const card of cards) {
    const page = pages.at(-1)
    if (page && used + markdownSizeOf(card) <= FREEFORM_MARKDOWN_BUDGET) {
      page.push(card)
      used += markdownSizeOf(card)
    } else {
      pages.push([card])
      used = markdownSizeOf(card)
    }
  }
  return pages
}

/** How the person has laid the cards pane out. */
export type CardsLook = { page: number; isDismissedOpen: boolean; columns: number }

/** What each press in the cards pane does. */
export type CardsActs = { setCard: (id: string, isDismissed: boolean) => void; toPage: (page: number) => void; toggleDismissed: () => void }

export function drawCards(ui: ElementTable, surface: RenderSurface, b: DebriefBand | null, look: CardsLook, acts: CardsActs): RenderElement {
  const { Box, Text, Markdown } = ui
  const k = kitOf(ui, surface)
  const cards = b?.freeform ?? []
  if (!b || cards.length === 0) return <Text dimColor>No dashboard cards in this chat yet.</Text>

  const partOf = (part: DebriefFreeformPart, isDim: boolean) =>
    part.kind === 'markdown' ? <Markdown dimColor={isDim || undefined} text={part.text} /> : k.diagram(part)
  const cardOf = (card: DebriefFreeform) => {
    if (card.isDismissed) return k.stub(`card-${card.id}`, card.title, `undismiss-${card.id}`, () => acts.setCard(card.id, false))
    const title = (
      <Text bold dimColor={card.isRetired || undefined} wrap="truncate">
        {card.title}
      </Text>
    )
    // A card a rebuild took in as dismissed has no 🗑 of its own.
    const actions = card.isRetired ? [] : [k.action(`dismiss-${card.id}`, GLYPHS.dismiss, 'Dismiss the card', () => acts.setCard(card.id, true), { hintAt: 'below' })]
    return k.stack(`card-${card.id}`, [
      k.row(`card-head-${card.id}`, title, { age: freeformAgeOf(card, b.turn), actions }),
      <Box flexDirection="column">
        {card.isOldFormat ? <Text dimColor>In the old format: ↻ rebuild rewrites this card.</Text> : card.parts.map(part => partOf(part, card.isRetired))}
      </Box>,
    ])
  }
  const current = cards.filter(card => !card.isRetired)
  const retired = cards.filter(card => card.isRetired)
  // Cards a rebuild took in as dismissed fold behind one toggle; unfolded, they follow the others on the same pages.
  const listed = look.isDismissedOpen ? [...current, ...retired] : current
  const pages = cardPagesOf(listed)
  const page = Math.max(0, Math.min(look.page, pages.length - 1))
  const shown = pages[page] ?? []
  const first = pages.slice(0, page).reduce((count, cardsOnPage) => count + cardsOnPage.length, 1)
  const last = first + shown.length - 1
  const dismissedCount = `${retired.length} dismissed card${retired.length === 1 ? '' : 's'}`
  // The toggle sits where the dismissed cards begin: before the first of them, or after the last page's cards.
  const toggle = (isFirstOfPage: boolean) => [
    !isFirstOfPage && k.divider('rule-dismissed', look.columns),
    k.disclosure('freeform-dismissed', dismissedCount, look.isDismissedOpen, acts.toggleDismissed),
  ]
  // A rule between cards, as siblings of the cards, so the pane's row gap keeps each one clear of a card's buttons.
  const rows = shown.flatMap((card, index) => [
    ...(card === retired[0] ? toggle(index === 0) : [index > 0 && k.divider(`rule-${card.id}`, look.columns)]),
    cardOf(card),
  ])
  const isToggleAtEnd = retired.length > 0 && !look.isDismissedOpen && page === Math.max(0, pages.length - 1)

  return k.stack('freeform-cards', [
    current.length === 0 && <Text dimColor>Every card in this chat is dismissed.</Text>,
    pages.length > 1 &&
      k.heading('freeform-pager', <Text dimColor>{first === last ? `Card ${first} of ${listed.length}` : `Cards ${first}–${last} of ${listed.length}`}</Text>, [
        page > 0 && k.action('freeform-previous', GLYPHS.previous, 'Previous cards', () => acts.toPage(page - 1), { hintAt: 'below' }),
        page < pages.length - 1 && k.action('freeform-next', GLYPHS.next, 'Next cards', () => acts.toPage(page + 1), { hintAt: 'below' }),
      ]),
    ...rows,
    ...(isToggleAtEnd ? toggle(shown.length === 0) : []),
  ])
}

/** What the settings pane shows: the settings, the note under each field, the model being checked. */
export type SettingsLook = { shown: DebriefSettingsShown | null; notes: DebriefSettingsNotes; modelIdRow: number; checking: string | null }

/** What each change in the settings pane does: a pick from the list, or a typed model id or time limit. */
export type SettingsActs = { pick: (model: string) => void; change: (change: { model?: string; timeoutSeconds?: string }) => void }

export function drawSettings(ui: ElementTable, look: SettingsLook, acts: SettingsActs): RenderElement {
  const { Box, Text } = ui
  const { shown, notes, modelIdRow, checking } = look
  if (!shown) return <Text dimColor>{`Open the settings with /${SETTINGS_COMMAND}.`}</Text>
  // The mobile app draws no field yet.
  if (!('Select' in ui) || !('Input' in ui)) return <Text>{`Model: ${shown.model} · time limit: ${shown.timeoutSeconds} seconds`}</Text>
  const { Select, Input } = ui
  const noteOf = (field: keyof DebriefSettingsNotes) => {
    const note = notes[field]
    return (
      note && (
        <Box key={`settings-${field}-note`}>
          <Text wrap="wrap" color={note.isRefusal ? textColorOf(COLORS.red) : undefined} dimColor={!note.isRefusal || undefined}>
            {note.text}
          </Text>
        </Box>
      )
    )
  }
  // A model being checked shows in the picker meanwhile, even one typed in Other model.
  const models = checking && !shown.choices.includes(checking) ? [...shown.choices, checking] : shown.choices
  const choices = models.map(model => ({ value: model, label: model === shown.model ? `${model} (in use)` : model }))
  return (
    <Box flexDirection="column" gap={1}>
      <Text dimColor wrap="wrap">
        The model that rebuilds every chat's dashboard, and how long one rebuild may run.
      </Text>
      <Select key="settings-model" label="Model" options={choices} value={checking ?? shown.model} onSelect={acts.pick} />
      <Box key={`settings-model-id-row-${modelIdRow}`}>
        <Input
          key="settings-model-id"
          label="Other model"
          value=""
          placeholder="a full model id, such as claude-haiku-5-5"
          submitLabel="save"
          onSubmit={value => acts.change({ model: value })}
        />
      </Box>
      {noteOf('model')}
      <Input
        key="settings-timeout"
        label="Time limit, seconds"
        value={String(shown.timeoutSeconds)}
        submitLabel="save"
        onSubmit={value => acts.change({ timeoutSeconds: value })}
      />
      {noteOf('timeout')}
    </Box>
  )
}
