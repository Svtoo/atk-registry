import { expect, test } from 'claude-code/testing'
import {
  ASK_TEXTS,
  BULLETS,
  CHAT_DIR,
  ERRORS,
  FLAG_COLOR,
  markdownTexts,
  MODEL,
  mountBand,
  noticeRows,
  NOW_S,
  RESOLVED_ERROR,
  RISK_COLOR,
  SETTINGS_PANE,
  SHOWN_ERRORS,
  shownText,
  SIGNED_OUT_ERROR,
  SIGNED_OUT_STEPS,
  SIGNED_OUT_TITLE,
  SIGNED_OUT_WHAT,
  statusChipOf,
  TIMEOUT_ERROR,
  TIMEOUT_STEP,
  TIMEOUT_TITLE,
  TIMEOUT_WHAT,
  world,
} from './world'

test('the status chip shows its dot and the dashboard\'s age, and rebuild runs one in the session', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  w.files[`${CHAT_DIR}/tail-${MODEL.turn % 3}.json`] = JSON.stringify({ turn: MODEL.turn, rows: [{ role: 'user', text: 'Check the band.' }] })
  const ui = await mountBand($, w)
  expect(await statusChipOf(ui)).toEqual(['🟢 3m', 'current · 3m'])
  // When
  await ui.press({ key: 'rebuild' })
  await w.clock.settle()
  // Then
  expect(w.requests).toHaveLength(1)
  expect(w.state.rebuiltAt).toBe(NOW_S)
  expect(await statusChipOf(ui)).toEqual(['🟢 0s', 'current · 0s'])
  await ui.unmount()
})

test('a dashboard behind its turns shows its age in the chip and says how far behind in the hint', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  w.state.turns = { count: MODEL.turn + 1, endedAt: NOW_S, prompts: [] }
  // When
  const ui = await mountBand($, w)
  // Then
  expect(await statusChipOf(ui)).toEqual(['🟡 3m', 'behind 1 turn'])
  await ui.unmount()
})

test('the terminal, which has no pointer, keeps the status chip\'s word', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  w.state.regenErrors = ERRORS
  // When
  const ui = await mountBand($, w, 'terminal')
  // Then
  expect(await statusChipOf(ui)).toEqual(['🔴 2 × signed out', undefined])
  await ui.unmount()
})

test('a dashboard that lacks a recorded turn rebuilds when the band first draws, even when that turn ended while a rebuild ran', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  w.answers.push(() => new Promise<string>(() => {}))
  w.state.turns = { count: MODEL.turn + 1, endedAt: (w.state.rebuiltAt ?? 0) - 10, prompts: [] }
  w.files[`${CHAT_DIR}/tail-${(MODEL.turn + 1) % 3}.json`] = JSON.stringify({ turn: MODEL.turn + 1, rows: [{ role: 'user', text: 'Check.' }] })
  // When
  const ui = await mountBand($, w)
  // Then
  expect([w.requests.length, ...(await statusChipOf(ui))]).toEqual([1, '🔵 0s', 'updating · 0s'])
  expect(w.toasts).toEqual([])
  await ui.unmount()
})

test('a rebuild in progress says how long it has run', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  w.files[`${CHAT_DIR}/tail-${MODEL.turn % 3}.json`] = JSON.stringify({ turn: MODEL.turn, rows: [{ role: 'user', text: 'Check the band.' }] })
  w.answers.push(() => new Promise<string>(() => {}))
  const ui = await mountBand($, w)
  await ui.press({ key: 'rebuild' })
  // When
  await w.clock.advance(40_000)
  // Then
  expect(await statusChipOf(ui)).toEqual(['🔵 40s', 'updating · 40s'])
  await ui.unmount()
})

test('open rebuild failures name themselves in the chip\'s hint, with how many there are', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  w.state.regenErrors = ERRORS
  // When
  const ui = await mountBand($, w)
  // Then
  expect(await statusChipOf(ui)).toEqual(['🔴 3m', '2 × signed out'])
  // When
  w.state.regenErrors = [TIMEOUT_ERROR]
  w.state.mtimeMs += 1
  await w.clock.advance(2_000)
  // Then
  expect(await statusChipOf(ui)).toEqual(['🔴 3m', 'took too long'])
  await ui.unmount()
})

test('the status chip opens the status view under the header, filled while open, and closes it again', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  w.state.regenErrors = ERRORS
  const ui = await mountBand($, w)
  expect(await noticeRows(ui)).toEqual([])
  // When
  await ui.press({ key: 'status' })
  // Then
  expect((await ui.find({ key: 'view-status-title' }))?.text).toBe('🔴 Status· 2 × signed out')
  expect(await noticeRows(ui)).toEqual(SHOWN_ERRORS.map(error => `notice-${error.id}`))
  expect(await ui.find({ key: 'status-stats' })).toBeUndefined()
  expect((await ui.find({ key: 'status' }))?.props.variant).toBe('primary')
  // When
  await ui.press({ key: 'status' })
  // Then
  expect(await ui.find({ key: 'view-status' })).toBeUndefined()
  expect((await ui.find({ key: 'status' }))?.props.dimColor).toBe(true)
  await ui.unmount()
})

test('the panel lists each open problem: what it is, how often and when, and the numbered steps that fix it', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  w.state.regenErrors = ERRORS
  const ui = await mountBand($, w)
  // When
  await ui.press({ key: 'status' })
  // Then
  expect(await noticeRows(ui)).toEqual(SHOWN_ERRORS.map(error => `notice-${error.id}`))
  expect(await ui.find({ key: 'resolved-toggle' })).toBeUndefined()
  expect(await shownText(ui, `notice-head-${SIGNED_OUT_ERROR.id}`)).toBe(`${SIGNED_OUT_TITLE}2m ago▸❝`)
  expect(await shownText(ui, `notice-head-${TIMEOUT_ERROR.id}`)).toBe(`${TIMEOUT_TITLE}× 2 · 10m ago▸❝🗑`)
  const markers = (await ui.findAll({ type: 'Svg' }))
    .filter((svg: { props: { alt: string } }) => ['blocked', 'degraded'].includes(svg.props.alt))
    .map((svg: { props: { alt: string; source: string } }) => [svg.props.alt, svg.props.source.match(/<path[^>]*fill="([^"]+)"/)?.[1]])
  expect(markers).toEqual([
    ['blocked', RISK_COLOR],
    ['degraded', FLAG_COLOR],
  ])
  expect((await ui.find({ type: 'Text', text: TIMEOUT_WHAT }))?.props.dimColor).toBe(true)
  expect((await ui.find({ key: `step-${SIGNED_OUT_ERROR.id}-1` }))?.text).toBe(`1.${SIGNED_OUT_STEPS[0]}`)
  expect((await ui.find({ key: `step-${SIGNED_OUT_ERROR.id}-2` }))?.text).toBe(`2.${SIGNED_OUT_STEPS[1]}`)
  expect(await markdownTexts(ui)).toEqual([...BULLETS, ...ASK_TEXTS])
  await ui.unmount()
})

test('dismiss sets a problem aside in the chat\'s state and leaves a stub with undo; undo brings it back', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  w.state.regenErrors = ERRORS
  const ui = await mountBand($, w)
  await ui.press({ key: 'status' })
  // When
  await ui.press({ key: `dismiss-notice-${TIMEOUT_ERROR.id}` })
  await w.clock.settle()
  // Then
  expect(w.state.regenErrors.map(error => [error.id, error.ackedAt])).toEqual([
    [TIMEOUT_ERROR.id, NOW_S],
    [SIGNED_OUT_ERROR.id, null],
  ])
  expect(await noticeRows(ui)).toEqual([`notice-${SIGNED_OUT_ERROR.id}`])
  const stub = await ui.find({ type: 'Text', text: TIMEOUT_TITLE })
  expect([stub?.props.strikethrough, stub?.props.dimColor]).toEqual([true, true])
  expect((await ui.find({ key: `undismiss-${TIMEOUT_ERROR.id}` }))?.props.label).toBe('↶')
  // When
  await ui.press({ key: `undismiss-${TIMEOUT_ERROR.id}` })
  await w.clock.settle()
  // Then
  expect(w.state.regenErrors.map(error => error.ackedAt)).toEqual([null, null])
  expect(await noticeRows(ui)).toEqual(SHOWN_ERRORS.map(error => `notice-${error.id}`))
  expect(await ui.find({ key: `undismiss-${TIMEOUT_ERROR.id}` })).toBeUndefined()
  await ui.unmount()
})

// As claude-dashboard saved its problems: no code, count or last time, and the oldest with no resolved time at all.
const OLD_TIMEOUT = { id: 'err-1799999400-0000000e', at: NOW_S - 600, kind: 'RegenTimeout', message: 'claude -p exceeded 180s wall-clock and was killed (ran 180.0s); produced nothing', ackedAt: null, resolvedAt: null }
const OLD_FAILURE = { id: 'err-1799996400-0000000f', at: NOW_S - 3600, kind: 'SubprocessFailed', message: 'claude -p exited with code 1', ackedAt: null }

test('problems claude-dashboard saved show as open, with their age and what they were, and a dismiss saves them whole', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  w.state.regenErrors = [OLD_FAILURE, OLD_TIMEOUT] as unknown as typeof w.state.regenErrors
  const ui = await mountBand($, w)
  await ui.press({ key: 'status' })
  // Then
  expect(await noticeRows(ui)).toEqual([`notice-${OLD_TIMEOUT.id}`, `notice-${OLD_FAILURE.id}`])
  expect(await shownText(ui, `notice-head-${OLD_TIMEOUT.id}`)).toBe(`${TIMEOUT_TITLE}10m ago▸❝🗑`)
  expect(await shownText(ui, `notice-head-${OLD_FAILURE.id}`)).toBe('A rebuild of this dashboard did not finish.1h ago▸❝🗑')
  expect(await ui.find({ key: 'resolved-toggle' })).toBeUndefined()
  // When
  await ui.press({ key: `dismiss-notice-${OLD_FAILURE.id}` })
  await w.clock.settle()
  // Then
  expect(w.state.regenErrors).toEqual([
    { ...OLD_FAILURE, lastAt: OLD_FAILURE.at, count: 1, code: 'rebuild.failed', ackedAt: NOW_S, resolvedAt: null },
    { ...OLD_TIMEOUT, lastAt: OLD_TIMEOUT.at, count: 1, code: 'rebuild.timeout' },
  ])
  await ui.unmount()
})

test('details on a problem shows its diagnostics and the technical detail', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  w.state.regenErrors = ERRORS
  const ui = await mountBand($, w)
  await ui.press({ key: 'status' })
  expect(await ui.find({ key: `notice-detail-${TIMEOUT_ERROR.id}` })).toBeUndefined()
  // When
  await ui.press({ key: `notice-details-${TIMEOUT_ERROR.id}` })
  // Then
  expect((await ui.find({ key: `notice-detail-${TIMEOUT_ERROR.id}` }))?.text).toBe(
    `Failure: ${TIMEOUT_ERROR.code} · Kind: ${TIMEOUT_ERROR.kind}\`\`\`\n${TIMEOUT_ERROR.message}\n\`\`\``,
  )
  expect((await ui.find({ key: `notice-details-${TIMEOUT_ERROR.id}` }))?.props.label).toBe('▾')
  // When
  await ui.press({ key: `notice-details-${TIMEOUT_ERROR.id}` })
  // Then
  expect(await ui.find({ key: `notice-detail-${TIMEOUT_ERROR.id}` })).toBeUndefined()
  await ui.unmount()
})

test('problems that resolved on their own fold behind a count, each with when it resolved', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  w.state.regenErrors = [RESOLVED_ERROR]
  const ui = await mountBand($, w)
  await ui.press({ key: 'status' })
  expect((await ui.find({ key: 'resolved-toggle' }))?.props.label).toBe('▸ 1 resolved')
  expect(await ui.find({ key: `resolved-${RESOLVED_ERROR.id}` })).toBeUndefined()
  // When
  await ui.press({ key: 'resolved-toggle' })
  // Then
  expect((await ui.find({ key: `resolved-${RESOLVED_ERROR.id}` }))?.text).toBe(`${TIMEOUT_TITLE}resolved 1h ago`)
  expect((await ui.find({ key: 'resolved-toggle' }))?.props.label).toBe('▾ 1 resolved')
  await ui.unmount()
})

test('a problem the settings can end has a settings button on its step, which opens the settings pane', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  w.state.regenErrors = [TIMEOUT_ERROR]
  const ui = await mountBand($, w)
  await ui.press({ key: 'status' })
  // Then
  expect((await ui.find({ key: `step-${TIMEOUT_ERROR.id}-1` }))?.text).toBe(`1.${TIMEOUT_STEP}⚙ settings`)
  // When
  await ui.press({ key: `settings-${TIMEOUT_ERROR.id}` })
  await w.clock.settle()
  // Then
  expect(w.opened).toEqual([`${SETTINGS_PANE}: ATK Debrief settings (focus)`])
  await ui.unmount()
})

test('reply puts the problem, quoted, into the prompt box: what it is, the steps that fix it and the detail', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  w.state.regenErrors = ERRORS
  const ui = await mountBand($, w)
  await ui.press({ key: 'status' })
  // When
  await ui.press({ key: `reply-notice-${SIGNED_OUT_ERROR.id}` })
  // Then
  expect(w.fills).toEqual([
    `> Dashboard problem: ${SIGNED_OUT_TITLE} ${SIGNED_OUT_WHAT} Steps: 1) ${SIGNED_OUT_STEPS[0]} 2) ${SIGNED_OUT_STEPS[1]} Detail: ${SIGNED_OUT_ERROR.message}\n\n`,
  ])
  await ui.unmount()
})

test('a dismissed problem is kept in the chat\'s state: its stub shows after a reload, once however often it is pressed', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  w.state.regenErrors = [{ ...TIMEOUT_ERROR, ackedAt: NOW_S - 30 }, SIGNED_OUT_ERROR]
  // When
  const ui = await mountBand($, w)
  await ui.press({ key: 'status' })
  // Then
  expect((await ui.findAll({ key: `dismissed-${TIMEOUT_ERROR.id}` })).length).toBe(1)
  expect((await ui.find({ key: `undismiss-${TIMEOUT_ERROR.id}` }))?.props.label).toBe('↶')
  await ui.unmount()
})

test('a dismissed problem leaves with the next rebuild that succeeds, as the other stubs do', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  w.files[`${CHAT_DIR}/tail-${MODEL.turn % 3}.json`] = JSON.stringify({ turn: MODEL.turn, rows: [{ role: 'user', text: 'Check.' }] })
  w.state.regenErrors = [{ ...TIMEOUT_ERROR, ackedAt: NOW_S - 30 }]
  const ui = await mountBand($, w)
  await ui.press({ key: 'status' })
  // When
  await ui.press({ key: 'rebuild' })
  await w.clock.settle()
  // Then
  expect(await ui.find({ key: `dismissed-${TIMEOUT_ERROR.id}` })).toBeUndefined()
  expect(w.state.regenErrors.map((error: { resolvedAt: number | null }) => error.resolvedAt)).toEqual([NOW_S])
  await ui.unmount()
})

test('with no open problem, the status view says so', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  const ui = await mountBand($, w)
  // When
  await ui.press({ key: 'status' })
  // Then
  expect((await ui.find({ key: 'status-empty' }))?.text).toBe('✓ No problems')
  await ui.unmount()
})

test('a problem to report links to where reports go', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  w.state.regenErrors = [{ ...TIMEOUT_ERROR, id: 'err-1800000000-0000000b', code: 'rebuild.bad_output', kind: 'rejected' }]
  const ui = await mountBand($, w)
  // When
  await ui.press({ key: 'status' })
  // Then
  expect(await markdownTexts(ui)).toContain('[report it](https://github.com/Svtoo/atk-registry/issues)')
  await ui.unmount()
})
