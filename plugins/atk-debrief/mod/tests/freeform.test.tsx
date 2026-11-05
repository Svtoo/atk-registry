import { expect, test } from 'claude-code/testing'
import {
  CARDS_MODEL,
  DESIGN_CARD,
  DESIGN_TABLE,
  type Freeform,
  FREEFORM_PANE,
  HTML_CARD,
  MODEL,
  type Model,
  mountBand,
  mountPane,
  RETIRED_CARD,
  shownText,
  unmountAll,
  world,
} from './world'

test('the header counts the Freeform cards in a chip; a dismissed card does not count', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, CARDS_MODEL)
  // When
  const ui = await mountBand($, w)
  // Then
  expect((await ui.find({ key: 'freeform' }))?.props.label).toBe('🧩 2')
  await ui.unmount()
})

test('a card the user just dismissed leaves the chip count at once', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, CARDS_MODEL)
  w.state.verdicts[`freeform:${DESIGN_CARD.id}`] = { verdict: 'dismissed' }
  // When
  const ui = await mountBand($, w)
  // Then
  expect((await ui.find({ key: 'freeform' }))?.props.label).toBe('🧩 1')
  await ui.unmount()
})

test('a diagram with no size or namespace takes its size from its viewBox, gets the SVG namespace, and is named by its title', { timeoutMs: 20_000 }, async ($, on) => {
  const bare = '<svg viewBox="0 0 120 30"><title>the flow</title><rect width="10" height="10"/></svg>'
  const w = world(on, { ...MODEL, freeform: [{ id: 'f8', body: `## Bare\n\n${bare}`, changed_turn: 1, dismissed_turn: 0 }] })
  // When
  const { band, pane } = await mountPane($, w)
  // Then
  const diagram = await pane.find({ type: 'Svg' })
  expect([diagram?.props.alt, diagram?.props.width, diagram?.props.height]).toEqual(['the flow', 120, 30])
  expect(diagram?.props.source.startsWith('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 30"><style>')).toBe(true)
  await unmountAll(pane, band)
})

test('a card holding control characters still draws in the pane, without them', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, freeform: [{ id: 'f9', body: '## Logs\n\nThe run printed \u001b[32mOK\u001b[0m.', changed_turn: 1, dismissed_turn: 0 }] })
  // When
  const { band, pane } = await mountPane($, w)
  // Then
  const texts = (await pane.findAll({ type: 'Markdown' })).map((markdown: { props: { text: string } }) => markdown.props.text)
  expect(texts.join('\n')).toContain('The run printed OK.')
  await unmountAll(pane, band)
})

const ALL_DISMISSED_MODEL: Model = { ...MODEL, freeform: [{ ...DESIGN_CARD, dismissed_turn: 20 }, RETIRED_CARD] }

test('when every card is dismissed the chip stays, naming them, and opens the pane', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, ALL_DISMISSED_MODEL)
  const ui = await mountBand($, w)
  expect((await ui.find({ key: 'freeform' }))?.props.label).toBe('🧩 2 dismissed')
  // When
  await ui.press({ key: 'freeform' })
  await w.clock.settle()
  // Then
  expect(w.opened).toEqual([`${FREEFORM_PANE}: ATK Debrief (focus)`])
  await ui.unmount()
})

test('a pane where every card is dismissed says so and folds them', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, ALL_DISMISSED_MODEL)
  // When
  const { band, pane } = await mountPane($, w)
  // Then
  expect((await pane.find({ type: 'Text', text: /dismissed\.$/ }))?.text).toBe('Every card in this chat is dismissed.')
  expect((await pane.find({ key: 'freeform-dismissed' }))?.props.label).toBe('▸ 2 dismissed cards')
  expect(await pane.find({ type: 'Text', text: 'A retired sketch' })).toBeUndefined()
  await unmountAll(pane, band)
})

test('the dismissed chip opens the pane with those cards unfolded, and the toggle folds them', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, ALL_DISMISSED_MODEL)
  const { band, pane } = await mountPane($, w)
  // When
  await band.press({ key: 'freeform' })
  await w.clock.settle()
  // Then
  expect((await pane.find({ key: 'freeform-dismissed' }))?.props.label).toBe('▾ 2 dismissed cards')
  expect((await pane.find({ type: 'Text', text: 'Design of the band' }))?.props.dimColor).toBe(true)
  const ages = (await pane.findAll({ type: 'Text', text: /^dismissed/ })).map((text: { text: string }) => text.text)
  expect(ages).toEqual(['dismissed 1 turn ago', 'dismissed 12 turns ago'])
  // When
  await pane.press({ key: 'freeform-dismissed' })
  await w.clock.settle()
  // Then
  expect((await pane.find({ key: 'freeform-dismissed' }))?.props.label).toBe('▸ 2 dismissed cards')
  expect(await pane.find({ type: 'Text', text: 'Design of the band' })).toBeUndefined()
  await unmountAll(pane, band)
})

test('a pane left open after the cards are gone keeps a chip that reads 🧩 0', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, CARDS_MODEL)
  const ui = await mountBand($, w)
  // When
  w.state.model = MODEL
  w.state.mtimeMs += 1
  await w.clock.advance(2_000)
  // Then
  expect((await ui.find({ key: 'freeform' }))?.props.label).toBe('🧩 0')
  await ui.unmount()
})

test('a chat with no Freeform cards has no chip', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  // When
  const ui = await mountBand($, w)
  // Then
  expect(await ui.find({ key: 'freeform' })).toBeUndefined()
  await ui.unmount()
})

test('the chip closes the Freeform pane and opens it again, in front', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, CARDS_MODEL)
  const ui = await mountBand($, w)
  // When
  await ui.press({ key: 'freeform' })
  await w.clock.settle()
  // Then
  expect(w.closed).toEqual([FREEFORM_PANE])
  expect((await ui.find({ key: 'freeform' }))?.props.dimColor).toBe(true)
  // When
  await ui.press({ key: 'freeform' })
  await w.clock.settle()
  // Then
  expect(w.opened.at(-1)).toBe(`${FREEFORM_PANE}: ATK Debrief (focus)`)
  expect((await ui.find({ key: 'freeform' }))?.props.variant).toBe('primary')
  await ui.unmount()
})

test('the pane opens by itself, without the keyboard, when the chat has Freeform cards', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, CARDS_MODEL)
  // When
  const ui = await mountBand($, w)
  // Then
  expect(w.opened).toEqual([`${FREEFORM_PANE}: ATK Debrief`])
  expect((await ui.find({ key: 'freeform' }))?.props.variant).toBe('primary')
  await ui.unmount()
})

test('a chat with no Freeform cards opens no pane', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  // When
  const ui = await mountBand($, w)
  await w.clock.advance(2_000)
  // Then
  expect(w.opened).toEqual([])
  await ui.unmount()
})

test('a pane the person closed stays closed until a card is new or changes', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, CARDS_MODEL)
  const ui = await mountBand($, w)
  await ui.press({ key: 'freeform' })
  await w.clock.advance(2_000)
  expect(w.opened.length).toBe(1)
  // When
  w.state.model = { ...CARDS_MODEL, freeform: [{ ...DESIGN_CARD, changed_turn: 20 }, HTML_CARD, RETIRED_CARD] }
  w.state.mtimeMs += 1
  await w.clock.advance(2_000)
  // Then
  expect(w.opened).toEqual([`${FREEFORM_PANE}: ATK Debrief`, `${FREEFORM_PANE}: ATK Debrief`])
  expect((await ui.find({ key: 'freeform' }))?.props.variant).toBe('primary')
  await ui.unmount()
})

test('a card that only goes away opens nothing', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, CARDS_MODEL)
  const ui = await mountBand($, w)
  await ui.press({ key: 'freeform' })
  // When
  w.state.model = { ...CARDS_MODEL, freeform: [DESIGN_CARD, { ...HTML_CARD, dismissed_turn: 21 }, RETIRED_CARD] }
  w.state.mtimeMs += 1
  await w.clock.advance(2_000)
  // Then
  expect(w.opened.length).toBe(1)
  expect((await ui.find({ key: 'freeform' }))?.props.label).toBe('🧩 1')
  await ui.unmount()
})

test('a pane the desktop does not place says why, and the chip stays closed', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, CARDS_MODEL)
  w.placement = { isPlaced: false, reason: 'no attached surface places panes' }
  const ui = await mountBand($, w)
  // When
  await ui.press({ key: 'freeform' })
  await w.clock.settle()
  // Then
  expect(w.toasts).toEqual(['Freeform cards not shown: no attached surface places panes'])
  expect((await ui.find({ key: 'freeform' }))?.props.dimColor).toBe(true)
  await ui.unmount()
})

test('the pane draws each card: its title, its age, its Markdown and its diagram in the theme colours', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, CARDS_MODEL)
  // When
  const { band, pane } = await mountPane($, w)
  // Then
  expect((await pane.find({ type: 'Text', text: 'Design of the band' }))?.props.bold).toBe(true)
  expect((await pane.find({ type: 'Text', text: /^updated/ }))?.text).toBe('updated 3 turns ago')
  const texts = (await pane.findAll({ type: 'Markdown' })).map((markdown: { props: { text: string } }) => markdown.props.text)
  expect(texts).toEqual(['The **band** reads the state.', DESIGN_TABLE])
  const [diagram] = await pane.findAll({ type: 'Svg' })
  expect([diagram?.props.alt, diagram?.props.width, diagram?.props.height]).toEqual(['agent to server', 200, 60])
  expect(diagram?.props.source).toContain('stroke="var(--accent)"')
  expect(diagram?.props.source).toMatch(/^<svg [^>]*><style>svg \{ --fg:[^}]*--accent:#6366f1[^}]*\}\s*@media \(prefers-color-scheme: dark\)/)
  await unmountAll(pane, band)
})

test('on the terminal a diagram is named, not drawn', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, CARDS_MODEL)
  // When
  const { band, pane } = await mountPane($, w, 'terminal')
  // Then
  expect(await pane.find({ type: 'Svg' })).toBeUndefined()
  expect((await pane.find({ type: 'Text', text: /^\[diagram/ }))?.text).toBe('[diagram: agent to server]')
  await unmountAll(pane, band)
})

test('a card still in the old HTML format says the next rebuild rewrites it', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, CARDS_MODEL)
  // When
  const { band, pane } = await mountPane($, w)
  // Then
  expect((await pane.find({ type: 'Text', text: 'Old card' }))?.props.bold).toBe(true)
  expect((await pane.find({ type: 'Text', text: /old format/ }))?.text).toBe('In the old format: ↻ rebuild rewrites this card.')
  const texts = (await pane.findAll({ type: 'Markdown' })).map((markdown: { props: { text: string } }) => markdown.props.text)
  expect(texts.some((text: string) => text.includes('<section'))).toBe(false)
  await unmountAll(pane, band)
})

test('a card saved under html, before cards had a body, shows its own title', { timeoutMs: 20_000 }, async ($, on) => {
  const { body, ...card } = HTML_CARD
  const w = world(on, { ...MODEL, freeform: [{ ...card, html: body } as unknown as Freeform] })
  // When
  const { band, pane } = await mountPane($, w)
  // Then
  expect((await pane.find({ type: 'Text', text: 'Old card' }))?.props.bold).toBe(true)
  await unmountAll(pane, band)
})

test('🗑 keeps the card as a struck line with ↶ until the next rebuild', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, CARDS_MODEL)
  const { band, pane } = await mountPane($, w)
  // When
  await pane.press({ key: `dismiss-${DESIGN_CARD.id}` })
  await w.clock.settle()
  // Then
  expect(w.state.verdicts[`freeform:${DESIGN_CARD.id}`]?.verdict).toBe('dismissed')
  expect(await pane.find({ type: 'Svg' })).toBeUndefined()
  expect((await pane.find({ type: 'Text', text: 'Design of the band' }))?.props.strikethrough).toBe(true)
  expect((await pane.find({ key: `undismiss-${DESIGN_CARD.id}` }))?.props.label).toBe('↶')
  // When
  await pane.press({ key: `undismiss-${DESIGN_CARD.id}` })
  await w.clock.settle()
  // Then
  expect(w.state.verdicts).toEqual({})
  expect(await pane.find({ type: 'Svg' })).toBeDefined()
  await unmountAll(pane, band)
})

test('cards a rebuild dismissed fold behind a toggle and, shown, say they are dismissed', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, CARDS_MODEL)
  const { band, pane } = await mountPane($, w)
  expect((await pane.find({ key: 'freeform-dismissed' }))?.props.label).toBe('▸ 1 dismissed card')
  expect(await pane.find({ type: 'Text', text: 'A retired sketch' })).toBeUndefined()
  // When
  await pane.press({ key: 'freeform-dismissed' })
  await w.clock.settle()
  // Then
  expect((await pane.find({ key: 'freeform-dismissed' }))?.props.label).toBe('▾ 1 dismissed card')
  expect((await pane.find({ type: 'Text', text: 'A retired sketch' }))?.props.dimColor).toBe(true)
  expect((await pane.find({ type: 'Text', text: /^dismissed/ }))?.text).toBe('dismissed 12 turns ago')
  expect(await pane.find({ key: `dismiss-${RETIRED_CARD.id}` })).toBeUndefined()
  await unmountAll(pane, band)
})

test('a long card is drawn in Markdown pieces that every build takes, split between paragraphs', { timeoutMs: 20_000 }, async ($, on) => {
  const paragraph = (n: number) => `Paragraph ${n} ${'y'.repeat(3_000)}`
  const paragraphs = Array.from({ length: 8 }, (_, n) => paragraph(n))
  const w = world(on, { ...MODEL, freeform: [{ id: 'f9', body: `## Long card\n\n${paragraphs.join('\n\n')}`, changed_turn: 1, dismissed_turn: 0 }] })
  // When
  const { band, pane } = await mountPane($, w)
  // Then
  const texts: string[] = (await pane.findAll({ type: 'Markdown' })).map((markdown: { props: { text: string } }) => markdown.props.text)
  expect(texts.length).toBe(3)
  expect(texts.every(text => text.length <= 10_000)).toBe(true)
  expect(texts.join('\n\n')).toBe(paragraphs.join('\n\n'))
  await unmountAll(pane, band)
})

test('a code block is never cut between two Markdown pieces', { timeoutMs: 20_000 }, async ($, on) => {
  const code = '```text\n' + 'line\n\n'.repeat(600) + '```'
  const w = world(on, { ...MODEL, freeform: [{ id: 'f7', body: `## Code\n\n${'z'.repeat(6_000)}\n\n${code}`, changed_turn: 1, dismissed_turn: 0 }] })
  // When
  const { band, pane } = await mountPane($, w)
  // Then
  const texts: string[] = (await pane.findAll({ type: 'Markdown' })).map((markdown: { props: { text: string } }) => markdown.props.text)
  expect(texts.length).toBe(2)
  expect(texts.map(text => text.split('```').length % 2)).toEqual([1, 1])
  await unmountAll(pane, band)
})

test('a pane with no cards says so', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  // When
  const { band, pane } = await mountPane($, w)
  // Then
  expect((await pane.find({ type: 'Text', text: /cards in this chat/ }))?.text).toBe('No dashboard cards in this chat yet.')
  await unmountAll(pane, band)
})

// Four cards of 30,000 characters each: one drawing holds three.
const bigCard = (n: number, changedTurn = 1): Freeform => ({ id: `b${n}`, body: `## Big card ${n}\n\n${'x'.repeat(30_000)}`, changed_turn: changedTurn, dismissed_turn: 0 })
const BIG_CARDS = [bigCard(1), bigCard(2), bigCard(3), bigCard(4)]
const cardTitles = async (pane: any) => (await pane.findAll({ type: 'Text', text: /^Big card/ })).map((title: { text: string }) => title.text)

test('cards past what one drawing holds go on further pages, with ← and → between them', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, freeform: BIG_CARDS })
  const { band, pane } = await mountPane($, w)
  // Then
  expect(await cardTitles(pane)).toEqual(['Big card 1', 'Big card 2', 'Big card 3'])
  expect(await shownText(pane, 'freeform-pager')).toBe('Cards 1–3 of 4→')
  // When
  await pane.press({ key: 'freeform-next' })
  // Then
  expect(await cardTitles(pane)).toEqual(['Big card 4'])
  expect(await shownText(pane, 'freeform-pager')).toBe('Card 4 of 4←')
  // When
  await pane.press({ key: 'freeform-previous' })
  // Then
  expect(await cardTitles(pane)).toEqual(['Big card 1', 'Big card 2', 'Big card 3'])
  await unmountAll(pane, band)
})

test('cards that fit one drawing show no pager', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, freeform: BIG_CARDS.slice(0, 3) })
  // When
  const { band, pane } = await mountPane($, w)
  // Then
  expect(await pane.find({ key: 'freeform-pager' })).toBeUndefined()
  await unmountAll(pane, band)
})

test('the pane opened by a changed card shows the page that card is on', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, freeform: BIG_CARDS })
  const { band, pane } = await mountPane($, w)
  // When
  w.state.model = { ...MODEL, freeform: [...BIG_CARDS.slice(0, 3), bigCard(4, 21)] }
  w.state.mtimeMs += 1
  await w.clock.advance(2_000)
  // Then
  expect(await cardTitles(pane)).toEqual(['Big card 4'])
  await unmountAll(pane, band)
})

test('dismissed cards, unfolded, go on pages as the others do, so none is cut off', { timeoutMs: 20_000 }, async ($, on) => {
  const retired = [5, 6, 7, 8, 9, 10, 11, 12].map(n => ({ ...bigCard(n), dismissed_turn: 2 }))
  const w = world(on, { ...MODEL, freeform: [bigCard(1), bigCard(2), ...retired] })
  const { band, pane } = await mountPane($, w)
  // When
  await pane.press({ key: 'freeform-dismissed' })
  const seen = new Set<string>(await cardTitles(pane))
  while (await pane.find({ key: 'freeform-next' })) {
    await pane.press({ key: 'freeform-next' })
    for (const title of await cardTitles(pane)) seen.add(title)
  }
  // Then
  expect([...seen].sort()).toEqual([1, 2, 5, 6, 7, 8, 9, 10, 11, 12].map(n => `Big card ${n}`).sort())
  await unmountAll(pane, band)
})
