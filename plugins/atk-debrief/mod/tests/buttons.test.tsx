import { expect, test } from 'claude-code/testing'
import {
  CARDS_MODEL,
  DESIGN_CARD,
  ERRORS,
  HEADSUPS,
  LINKS,
  type Model,
  MODEL,
  mountBand,
  mountPane,
  THEME_TEXTS,
  TODOS,
  unmountAll,
  world,
} from './world'

const EVERY_PART_MODEL: Model = { ...CARDS_MODEL, todo: TODOS, headsup: HEADSUPS, links: LINKS }

// The band opens one view at a time, so a look check draws the band once with each view open.
const VIEWS = ['headsups', 'todos', 'status', 'links'] as const
async function eachViewOf<T>(band: any, look: (drawn: any) => Promise<T[]> | T[]): Promise<T[]> {
  const found: T[] = []
  for (const view of VIEWS) {
    await band.press({ key: view })
    expect(await band.find({ key: `view-${view}` })).toBeTruthy()
    found.push(...(await look(band)))
  }
  return found
}

test('on the desktop every control in the band and the pane is a native button', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, EVERY_PART_MODEL)
  w.state.regenErrors = ERRORS
  // When
  const { band, pane } = await mountPane($, w)
  // Then
  const buttons = [...(await eachViewOf(band, ui => ui.findAll({ type: 'Button' }))), ...(await pane.findAll({ type: 'Button' }))]
  expect(buttons.length).toBeGreaterThan(40)
  expect(buttons.filter((button: { props: { plain?: true } }) => button.props.plain).map((button: { key?: string }) => button.key)).toEqual([])
  await unmountAll(pane, band)
})

for (const [surface, rowGap] of [['desktop', 1], ['terminal', undefined]] as const) {
  test(`rows with buttons, the asks, a view's and a problem's, are spaced on the ${surface} as its buttons need`, { timeoutMs: 20_000 }, async ($, on) => {
    const w = world(on, EVERY_PART_MODEL)
    w.state.regenErrors = ERRORS
    const band = await mountBand($, w, surface)
    const gapOf = async (key: string) => {
      const box = await band.find({ key })
      return box ? box.props.rowGap : 'not drawn'
    }
    // When
    await band.press({ key: 'todos' })
    // Then
    expect([await gapOf('asks'), await gapOf('view-todos')]).toEqual([rowGap, rowGap])
    // When
    await band.press({ key: 'status' })
    // Then
    expect([await gapOf('view-status'), await gapOf(`notice-${ERRORS[0]!.id}`)]).toEqual([rowGap, rowGap])
    await band.unmount()
  })

  test(`the cards pane spaces its rows with buttons on the ${surface} as the band does`, { timeoutMs: 20_000 }, async ($, on) => {
    const w = world(on, EVERY_PART_MODEL)
    // When
    const { band, pane } = await mountPane($, w, surface)
    // Then
    const boxes = [await pane.find({ key: 'freeform-cards' }), await pane.find({ key: `card-${DESIGN_CARD.id}` })]
    expect(boxes.map(box => (box ? box.props.rowGap : 'not drawn'))).toEqual([rowGap, rowGap])
    await unmountAll(pane, band)
  })
}

// Each box that holds a line cut to fit, as [its row's key, whether the row holds a button, its minWidth].
function truncatingBoxesOf(node: any, row: any = null): [string, boolean, unknown][] {
  if (!node || typeof node !== 'object') return []
  const hasButton = (tree: any): boolean => tree?.type === 'Button' || (tree?.children ?? []).some(hasButton)
  const holds = (node.children ?? []).some((child: any) => child?.type === 'Text' && child.props?.wrap === 'truncate')
  const own: [string, boolean, unknown][] = node.type === 'Box' && holds && row ? [[row.props?.key ?? '', hasButton(row), node.props?.minWidth]] : []
  const nextRow = node.type === 'Box' && node.props?.flexDirection === 'row' ? node : row
  return [...own, ...(node.children ?? []).flatMap((child: any) => truncatingBoxesOf(child, nextRow))]
}

test('a line cut to fit may shrink below its text, so the buttons after it stay in view; a divider is clipped, with no "…"', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, EVERY_PART_MODEL)
  w.state.regenErrors = ERRORS
  w.state.verdicts = {
    [`freeform:${DESIGN_CARD.id}`]: { verdict: 'dismissed' },
    [`cta:${MODEL.cta[0]!.id}`]: { verdict: 'dismissed' },
    [`todo:${TODOS[1]!.id}`]: { verdict: 'done' },
    [`todo:${TODOS[3]!.id}`]: { verdict: 'dropped' },
  }
  // When
  const { band, pane } = await mountPane($, w)
  // Then
  const boxes = [...truncatingBoxesOf(await band.drawn()), ...(await eachViewOf(band, async ui => truncatingBoxesOf(await ui.drawn()))), ...truncatingBoxesOf(await pane.drawn())]
  const dividers = boxes.filter(([key]) => key.startsWith('rule-'))
  const lines = boxes.filter(([key]) => !key.startsWith('rule-'))
  expect([lines.filter(([, hasButton]) => hasButton).length > 4, dividers.length > 0]).toEqual([true, true])
  expect(lines.filter(([, , minWidth]) => minWidth !== 0)).toEqual([])
  expect(dividers.filter(([, , minWidth]) => minWidth !== undefined)).toEqual([])
  await unmountAll(pane, band)
})

// Each hover hint in a drawn tree, as [the key of the control it names, its text, its rows from the control's top]: a
// hidden Box out of the flow, beside the control in the control's own keyed box, or in a keyed line it names.
function hintsOf(node: any): [string, string, number][] {
  if (!node || typeof node !== 'object') return []
  const children: any[] = node.children ?? []
  const hint = children.find(child => child?.type === 'Box' && child.props?.position === 'absolute' && child.props?.display === 'none')
  const textOf = (tree: any): string => (typeof tree === 'string' ? tree : (tree?.children ?? []).map(textOf).join(''))
  const own: [string, string, number][] = hint
    ? children.filter(child => child !== hint).map(child => [child?.props?.key || node.props?.key || '', textOf(hint).trim(), hint.props.top])
    : []
  return [...own, ...children.flatMap(hintsOf)]
}

test('on the desktop only the header\'s buttons carry a hint: the status chip its state, each glyph what it does; no row, line or pane control has one', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, EVERY_PART_MODEL)
  w.state.regenErrors = ERRORS
  w.state.verdicts = { [`cta:${MODEL.cta[0]!.id}`]: { verdict: 'dismissed' } }
  // When
  const { band, pane } = await mountPane($, w)
  // Then
  const trees = [await band.drawn(), ...(await eachViewOf(band, async ui => [await ui.drawn()])), await pane.drawn()]
  const hints = new Map(trees.flatMap(hintsOf).map(([key, text]) => [key, text]))
  expect([...hints.entries()]).toEqual([
    ['status', '2 × signed out'],
    ['settings', 'Open the settings'],
    ['rebuild', 'Rebuild the dashboard'],
    ['band-fold', 'Fold the band'],
  ])
  await unmountAll(pane, band)
})

test('a header hint shows below the header, where the band begins', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, EVERY_PART_MODEL)
  // When
  const band = await mountBand($, w)
  // Then
  const tops = new Map(hintsOf(await band.drawn()).map(([key, , top]) => [key, top]))
  expect([tops.get('rebuild')! > 0, tops.get('band-fold')! > 0]).toEqual([true, true])
  await band.unmount()
})

test('the terminal draws no hints: its buttons show their hotkeys instead', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, EVERY_PART_MODEL)
  // When
  const { band, pane } = await mountPane($, w, 'terminal')
  // Then
  expect([...hintsOf(await band.drawn()), ...hintsOf(await pane.drawn())]).toEqual([])
  await unmountAll(pane, band)
})

test('on the terminal the controls keep the plain look, which shows the hotkey', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, EVERY_PART_MODEL)
  // When
  const { band, pane } = await mountPane($, w, 'terminal')
  // Then
  const buttons = [...(await band.findAll({ type: 'Button' })), ...(await pane.findAll({ type: 'Button' }))]
  expect(buttons.length).toBeGreaterThan(10)
  expect(buttons.every((button: { props: { plain?: true } }) => button.props.plain === true)).toBe(true)
  expect((await band.find({ key: 'rebuild' }))?.props.hotkey).toBe('r')
  await unmountAll(pane, band)
})

// On the terminal an ask's number is white on its colour, which reads on either theme, so it keeps the hex.
const textColorsOf = async (ui: any): Promise<string[]> =>
  (await ui.findAll({ type: 'Text' }))
    .filter((text: { props: { color?: string; backgroundColor?: string } }) => text.props.color && !text.props.backgroundColor)
    .map((text: { props: { color: string } }) => text.props.color)

for (const surface of ['desktop', 'terminal'] as const) {
  test(`every coloured text in the band on the ${surface} names a theme key, so it follows a light or dark theme`, { timeoutMs: 20_000 }, async ($, on) => {
    const w = world(on, { ...MODEL, cta: [], headsup: HEADSUPS, todo: TODOS })
    w.state.regenErrors = ERRORS
    const ui = await mountBand($, w, surface)
    // When
    await ui.press({ key: 'status' })
    // Then
    const colors = await textColorsOf(ui)
    expect(colors.length).toBeGreaterThan(4)
    expect([...new Set(colors)].filter(color => !THEME_TEXTS.includes(color))).toEqual([])
    await ui.unmount()
  })
}
