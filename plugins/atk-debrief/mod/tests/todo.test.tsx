import { expect, test } from 'claude-code/testing'
import {
  ACTIVE_COLOR,
  ACTIVE_TEXT,
  ACTIVE_TODO,
  ASK_TEXTS,
  barWidthOf,
  BLOCKED_COLOR,
  BLOCKED_TODO,
  BULLETS,
  cellColorsOf,
  DONE_COLOR,
  DONE_TODO,
  doneRows,
  GREEN_TEXT,
  markdownStepOf,
  markdownTexts,
  MODEL,
  mountBand,
  NOW_S,
  OPEN_COLOR,
  OPEN_TEXT,
  OPEN_TODO,
  plainStepOf,
  RISK_TEXT,
  steps,
  todoBarOf,
  todoMarkersOf,
  todoRows,
  TODOS,
  UNSTAMPED_DONE_TODO,
  UNSTAMPED_OPEN_TODO,
  world,
} from './world'

// The alt of each mark drawn in the element with this key, as a step's cell names its status.
async function marksOf(ui: any, key: string): Promise<string[]> {
  const find = (node: any): any =>
    node && typeof node === 'object' ? ((node.props?.key ?? node.key) === key ? node : (node.children ?? []).map(find).find(Boolean)) : undefined
  const alts = (node: any): string[] => (!node || typeof node !== 'object' ? [] : [...(node.type === 'Svg' ? [node.props.alt] : []), ...(node.children ?? []).flatMap(alts)])
  return alts(find(await ui.drawn()))
}

test('the to-do peek line shows the plan as a bar, done steps first, then the count and the step in progress', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, todo: TODOS })
  // When
  const ui = await mountBand($, w)
  // Then
  const bar = await todoBarOf(ui)
  expect(bar?.props.alt).toBe('2 of 6 done')
  expect(bar?.props.width).toBe(barWidthOf(TODOS.length))
  expect(cellColorsOf(bar?.props.source ?? '')).toEqual([DONE_COLOR, DONE_COLOR, ACTIVE_COLOR, OPEN_COLOR, OPEN_COLOR, BLOCKED_COLOR])
  expect((await ui.find({ key: 'todos-peek' }))?.text).toBe(`2/6 · ${plainStepOf(ACTIVE_TODO)}`)
  expect((await ui.find({ type: 'Text', text: `2/6 · ${plainStepOf(ACTIVE_TODO)}` }))?.props.wrap).toBe('truncate')
  expect((await ui.find({ key: 'todos' }))?.props.label).toBe('📋 2/6')
  await ui.unmount()
})

test('with no step in progress, the line shows the next open step, not an earlier blocked one', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, todo: [DONE_TODO, BLOCKED_TODO, OPEN_TODO] })
  // When
  const ui = await mountBand($, w)
  // Then
  expect((await ui.find({ key: 'todos-peek' }))?.text).toBe(`1/3 · ${plainStepOf(OPEN_TODO)}`)
  await ui.unmount()
})

test('with only blocked steps left, the line shows the first blocked step', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, todo: [DONE_TODO, BLOCKED_TODO] })
  // When
  const ui = await mountBand($, w)
  // Then
  expect((await ui.find({ key: 'todos-peek' }))?.text).toBe(`1/2 · ${plainStepOf(BLOCKED_TODO)}`)
  await ui.unmount()
})

test('a plan of more than ten steps shows ten cells, each a tenth of the plan', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, todo: [...steps('done', 31), ...steps('active', 1), ...steps('open', 8), ...steps('blocked', 2)] })
  // When
  const ui = await mountBand($, w)
  // Then
  const bar = await todoBarOf(ui)
  expect(bar?.props.alt).toBe('31 of 42 done')
  expect(bar?.props.width).toBe(barWidthOf(10))
  // 31, 1, 8 and 2 of 42 steps are 7.4, 0.2, 1.9 and 0.5 tenths.
  expect(cellColorsOf(bar?.props.source ?? '')).toEqual([...Array(7).fill(DONE_COLOR), ...Array(2).fill(OPEN_COLOR), BLOCKED_COLOR])
  await ui.unmount()
})

test('the terminal draws the bar as coloured squares, an open step as a hollow one', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, todo: TODOS })
  // When
  const ui = await mountBand($, w, 'terminal')
  // Then
  const runs = (await ui.findAll({ type: 'Text' }))
    .filter((text: { text: string }) => /^[■□]+$/.test(text.text))
    .map((text: { text: string; props: { color: string } }) => ({ text: text.text, color: text.props.color }))
  expect(runs).toEqual([
    { text: '■■', color: GREEN_TEXT },
    { text: '■', color: ACTIVE_TEXT },
    { text: '□□', color: OPEN_TEXT },
    { text: '■', color: RISK_TEXT },
  ])
  await ui.unmount()
})

test('the peek line carries no button, and leaves while the to-do view is open', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, todo: TODOS })
  const ui = await mountBand($, w)
  expect((await ui.findAll({ type: 'Button' })).map((button: { key?: string }) => button.key).filter((key?: string) => key?.startsWith('todos-'))).toEqual([])
  // When
  await ui.press({ key: 'todos' })
  // Then
  expect(await ui.find({ key: 'todos-peek' })).toBeUndefined()
  await ui.unmount()
})

test('the 📋 chip opens the to-do view: a title row with the bar, the counts and the done toggle, then each step left in plan order, with its age and buttons', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, turn_base: 100, todo: TODOS })
  const ui = await mountBand($, w)
  // When
  await ui.press({ key: 'todos' })
  // Then
  expect((await ui.find({ key: 'view-todos-title' }))?.text).toBe('📋 To-do· 4 open · 2 done▸ 2 done')
  expect((await todoBarOf(ui))?.props.alt).toBe('2 of 6 done')
  expect(await todoRows(ui)).toEqual([`todo-${ACTIVE_TODO.id}`, `todo-${BLOCKED_TODO.id}`, `todo-${OPEN_TODO.id}`, `todo-${UNSTAMPED_OPEN_TODO.id}`])
  // The view opens under the header, above the last turn and the asks.
  expect(await markdownTexts(ui)).toEqual([...[ACTIVE_TODO, BLOCKED_TODO, OPEN_TODO, UNSTAMPED_OPEN_TODO].map(markdownStepOf), ...BULLETS, ...ASK_TEXTS])
  expect(await todoMarkersOf(ui)).toEqual([
    ['active', [ACTIVE_COLOR]],
    ['blocked', [BLOCKED_COLOR]],
    ['open', [OPEN_COLOR]],
    ['open', [OPEN_COLOR]],
  ])
  const ages = (await ui.findAll({ type: 'Text', text: /^(this turn|.* ago)$/ })).map((text: { text: string }) => text.text)
  expect(ages).toEqual(['16 turns ago', 'this turn', '1 turn ago'])
  expect((await ui.findAll({ type: 'Text' })).filter((text: { text: string }) => text.text === '')).toEqual([])
  expect((await ui.find({ type: 'Markdown', text: OPEN_TODO.text }))?.props.dimColor).toBe(false)
  expect((await ui.find({ key: `check-${ACTIVE_TODO.id}` }))?.props.label).toBe('✓')
  expect(await ui.find({ key: `check-${BLOCKED_TODO.id}` })).toBeUndefined()
  expect((await ui.find({ key: `drop-${BLOCKED_TODO.id}` }))?.props.label).toBe('🗑')
  expect((await ui.find({ key: 'todos' }))?.props.variant).toBe('primary')
  // When
  await ui.press({ key: 'todos' })
  // Then
  expect(await todoRows(ui)).toEqual([])
  expect((await ui.find({ key: 'todos' }))?.props.dimColor).toBe(true)
  await ui.unmount()
})

test('done steps fold behind a count on the title row, and show first, with when each was done', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, turn_base: 100, todo: TODOS })
  const ui = await mountBand($, w)
  await ui.press({ key: 'todos' })
  expect(await doneRows(ui)).toEqual([])
  expect((await ui.find({ key: 'done-toggle' }))?.props.label).toBe('▸ 2 done')
  // When
  await ui.press({ key: 'done-toggle' })
  // Then
  expect(await doneRows(ui)).toEqual([`done-${DONE_TODO.id}`, `done-${UNSTAMPED_DONE_TODO.id}`])
  const ages = (await ui.findAll({ type: 'Text', text: /^(this turn|.* ago)$/ })).map((text: { text: string }) => text.text)
  expect(ages).toEqual(['done 17 turns ago', '19 turns ago', '16 turns ago', 'this turn', '1 turn ago'])
  expect((await ui.find({ type: 'Markdown', text: DONE_TODO.text }))?.props.dimColor).toBe(true)
  expect(await ui.find({ key: `check-${DONE_TODO.id}` })).toBeUndefined()
  expect(await ui.find({ key: `drop-${DONE_TODO.id}` })).toBeUndefined()
  expect((await ui.find({ key: 'done-toggle' }))?.props.label).toBe('▾ 2 done')
  await ui.unmount()
})

test('✓ marks a step done in the chat\'s state; it stays in place, struck out, until the next rebuild, and ↶ takes it back', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, todo: TODOS })
  const ui = await mountBand($, w)
  await ui.press({ key: 'todos' })
  // When
  await ui.press({ key: `check-${ACTIVE_TODO.id}` })
  await w.clock.settle()
  // Then
  expect(w.state.verdicts).toEqual({ [`todo:${ACTIVE_TODO.id}`]: { verdict: 'done', at: NOW_S, turn: MODEL.turn, text: ACTIVE_TODO.text } })
  expect(await todoRows(ui)).toEqual([`todo-${ACTIVE_TODO.id}`, `todo-${BLOCKED_TODO.id}`, `todo-${OPEN_TODO.id}`, `todo-${UNSTAMPED_OPEN_TODO.id}`])
  const stub = await ui.find({ type: 'Text', text: plainStepOf(ACTIVE_TODO) })
  expect([stub?.props.strikethrough, stub?.props.dimColor]).toEqual([true, true])
  // Its green cell tells it from a dropped step until the rebuild takes it in.
  expect(await marksOf(ui, `todo-${ACTIVE_TODO.id}`)).toEqual(['done'])
  expect((await ui.find({ key: `uncheck-${ACTIVE_TODO.id}` }))?.props.label).toBe('↶')
  expect(await ui.find({ key: `check-${ACTIVE_TODO.id}` })).toBeUndefined()
  expect((await ui.find({ key: 'view-todos-title' }))?.text).toBe('📋 To-do· 3 open · 3 done▸ 2 done')
  // When
  await ui.press({ key: `uncheck-${ACTIVE_TODO.id}` })
  await w.clock.settle()
  // Then
  expect(w.state.verdicts).toEqual({})
  expect((await ui.find({ key: `check-${ACTIVE_TODO.id}` }))?.props.label).toBe('✓')
  await ui.unmount()
})

test('🗑 drops a step in the chat\'s state and leaves a struck-out stub with ↶; the bar and the counts leave it out', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, todo: TODOS })
  const ui = await mountBand($, w)
  await ui.press({ key: 'todos' })
  // When
  await ui.press({ key: `drop-${ACTIVE_TODO.id}` })
  await w.clock.settle()
  // Then
  expect(w.state.verdicts).toEqual({ [`todo:${ACTIVE_TODO.id}`]: { verdict: 'dropped', at: NOW_S, turn: MODEL.turn, text: ACTIVE_TODO.text } })
  expect(await todoRows(ui)).toEqual([`todo-${ACTIVE_TODO.id}`, `todo-${BLOCKED_TODO.id}`, `todo-${OPEN_TODO.id}`, `todo-${UNSTAMPED_OPEN_TODO.id}`])
  const stub = await ui.find({ type: 'Text', text: plainStepOf(ACTIVE_TODO) })
  expect([stub?.props.strikethrough, stub?.props.dimColor]).toEqual([true, true])
  expect((await ui.find({ key: `undrop-${ACTIVE_TODO.id}` }))?.props.label).toBe('↶')
  expect(await ui.find({ key: `check-${ACTIVE_TODO.id}` })).toBeUndefined()
  expect(await ui.find({ key: `drop-${ACTIVE_TODO.id}` })).toBeUndefined()
  expect((await ui.find({ key: 'view-todos-title' }))?.text).toBe('📋 To-do· 3 open · 2 done▸ 2 done')
  expect((await todoBarOf(ui))?.props.alt).toBe('2 of 5 done')
  // When
  await ui.press({ key: `undrop-${ACTIVE_TODO.id}` })
  await w.clock.settle()
  // Then
  expect(w.state.verdicts).toEqual({})
  expect((await ui.find({ key: `drop-${ACTIVE_TODO.id}` }))?.props.label).toBe('🗑')
  await ui.unmount()
})

test('with every step done, the chip still reaches the to-do, and no peek line shows', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, todo: [DONE_TODO, UNSTAMPED_DONE_TODO] })
  // When
  const ui = await mountBand($, w)
  // Then
  expect(await ui.find({ key: 'todos-peek' })).toBeUndefined()
  expect((await ui.find({ key: 'todos' }))?.props.label).toBe('📋 2/2')
  // When
  await ui.press({ key: 'todos' })
  // Then
  expect((await ui.find({ key: 'view-todos-title' }))?.text).toBe('📋 To-do· 0 open · 2 done▸ 2 done')
  await ui.unmount()
})

test('with every step dropped, the open view keeps the stubs but draws no bar', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, todo: [OPEN_TODO] })
  const ui = await mountBand($, w)
  await ui.press({ key: 'todos' })
  // When
  await ui.press({ key: `drop-${OPEN_TODO.id}` })
  await w.clock.settle()
  // Then
  expect(await todoBarOf(ui)).toBeUndefined()
  expect((await ui.find({ key: 'view-todos-title' }))?.text).toBe('📋 To-do· 0 open · 0 done')
  expect((await ui.find({ key: `undrop-${OPEN_TODO.id}` }))?.props.label).toBe('↶')
  await ui.unmount()
})

test('a plan that empties takes the to-do off the band, open view and all', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, todo: TODOS })
  const ui = await mountBand($, w)
  await ui.press({ key: 'todos' })
  // When
  w.state.model = MODEL
  w.state.mtimeMs += 1
  await w.clock.advance(2_000)
  // Then
  for (const key of ['todos', 'view-todos', 'todos-peek']) expect(await ui.find({ key })).toBeUndefined()
  await ui.unmount()
})

test('a plan with nothing done yet opens with no done toggle', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, todo: [ACTIVE_TODO, OPEN_TODO] })
  const ui = await mountBand($, w)
  // When
  await ui.press({ key: 'todos' })
  // Then
  expect(await ui.find({ key: 'done-toggle' })).toBeUndefined()
  expect(await todoRows(ui)).toEqual([`todo-${ACTIVE_TODO.id}`, `todo-${OPEN_TODO.id}`])
  await ui.unmount()
})

test('a long plan with steps left never shows a finished bar: the largest status left keeps a cell', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, todo: [...steps('done', 57), ...steps('open', 2), ...steps('blocked', 1)] })
  // When
  const ui = await mountBand($, w)
  // Then
  expect(cellColorsOf((await todoBarOf(ui))?.props.source ?? '')).toEqual([...Array(9).fill(DONE_COLOR), OPEN_COLOR])
  await ui.unmount()
})

test('a finished long plan fills every cell', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, todo: steps('done', 12) })
  // When
  const ui = await mountBand($, w)
  await ui.press({ key: 'todos' })
  // Then
  expect(cellColorsOf((await todoBarOf(ui))?.props.source ?? '')).toEqual(Array(10).fill(DONE_COLOR))
  await ui.unmount()
})

test('a dropped step has no cell, so it reads apart from a checked one', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, todo: TODOS })
  const ui = await mountBand($, w)
  await ui.press({ key: 'todos' })
  // When
  await ui.press({ key: `drop-${OPEN_TODO.id}` })
  await w.clock.settle()
  // Then
  expect(await marksOf(ui, `todo-${OPEN_TODO.id}`)).toEqual([])
  await ui.unmount()
})

test('with every step done and the done steps folded, the open view says so', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, todo: [DONE_TODO, UNSTAMPED_DONE_TODO] })
  const ui = await mountBand($, w)
  // When
  await ui.press({ key: 'todos' })
  // Then
  expect((await ui.find({ key: 'todos-empty' }))?.text).toBe('✓ Every step done')
  await ui.unmount()
})
