import { expect, test } from 'claude-code/testing'
import {
  ackedRows,
  ACTIVE_TEXT,
  ACTIVE_TODO,
  ASK_TEXTS,
  BAND,
  BULLETS,
  CHAT_DIR,
  circleFillOf,
  dismissedLinkRows,
  DONE_TODO,
  ERRORS,
  FLAG,
  FLAG_COLOR,
  FLAG_TEXT,
  GREEN_TEXT,
  type Headsup,
  headsupRows,
  HEADSUPS,
  ISSUE_LINK,
  ISSUE_MARKDOWN,
  linkRows,
  LINKS,
  markdownTexts,
  MODEL,
  mountBand,
  NEW_ASK,
  NEW_FLAG,
  NEWEST_ASK_COLOR,
  NOTEBOOK_LINK,
  NOTEBOOK_MARKDOWN,
  NOW_S,
  OLD_ASK,
  OLD_RISK,
  OLDEST_ASK_COLOR,
  OPEN_TODO,
  PR_LINK,
  PR_MARKDOWN,
  RISK_COLOR,
  RISK_TEXT,
  shownText,
  START,
  TIMEOUT_ERROR,
  type Todo,
  TODOS,
  world,
} from './world'

test('desktop band shows the header, the last turn and the numbered asks of this chat', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  // When
  const ui = await mountBand($, w)
  // Then
  expect(await ui.find({ type: 'Text', text: '📌' })).toBeUndefined()
  expect((await ui.find({ type: 'Text', text: /· 💬/ }))?.text).toBe(`· 💬 ${MODEL.turn}`)
  // The phase may be cut to fit; the turn after it keeps its width, so it never runs over what follows it.
  expect((await ui.find({ key: 'phase-label' }))?.props).toEqual({ key: 'phase-label', flexShrink: 1, minWidth: 0 })
  expect(await ui.find({ key: 'phase' })).toBeUndefined()
  expect(await markdownTexts(ui)).toEqual([...BULLETS, ...ASK_TEXTS])
  expect(await ui.find({ type: 'Text', text: /^Last turn/ })).toBeUndefined()
  expect(await ui.find({ key: 'links' })).toBeUndefined()
  expect((await ui.find({ key: 'asks-count' }))?.text).toBe(`📥 ${MODEL.cta.length}`)
  expect((await ui.find({ key: `reply-${OLD_ASK.id}` }))?.props.label).toBe('❝')
  expect((await ui.find({ key: `reply-${NEW_ASK.id}` }))?.props.label).toBe('❝')
  expect((await ui.find({ key: `dismiss-${OLD_ASK.id}` }))?.props.label).toBe('🗑')
  await ui.unmount()
})

test('a text holding control characters, as copied from coloured tool output, still draws, without them', { timeoutMs: 20_000 }, async ($, on) => {
  const ask = { id: 'c30', text: 'Tests print \u001b[31mFAIL\u001b[0m in red; check them?', created_turn: 21 }
  const w = world(on, { ...MODEL, cta: [...MODEL.cta, ask], last_turn: { bullets: ['Ran\u0007 the tests.'], turn: MODEL.turn } })
  // When
  const ui = await mountBand($, w)
  // Then
  expect(await ui.find({ key: 'ask-c30' })).toBeDefined()
  expect(await markdownTexts(ui)).toEqual(['Ran the tests.', ...ASK_TEXTS, 'Tests print FAIL in red; check them?'])
  await ui.unmount()
})

test('desktop numbers each ask in a round badge coloured by how long it has waited', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  // When
  const ui = await mountBand($, w)
  // Then
  const badges = (await ui.findAll({ type: 'Svg' })).map((badge: { props: { alt: string; source: string } }) => ({
    alt: badge.props.alt,
    fill: circleFillOf(badge.props.source),
  }))
  expect(badges).toEqual([
    { alt: 'ask 1', fill: OLDEST_ASK_COLOR },
    { alt: 'ask 2', fill: NEWEST_ASK_COLOR },
  ])
  await ui.unmount()
})

test('a narrow band cuts the phase to fit: the turn, the counts and the chips keep their width', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  // When
  const ui = await mountBand($, w)
  // Then
  const phase = await ui.find({ type: 'Text', text: 'Awaiting review' })
  expect(phase?.props.wrap).toBe('truncate')
  expect([(await ui.find({ key: 'turn' }))?.props.flexShrink, (await ui.find({ key: 'asks-count' }))?.props.flexShrink]).toEqual([0, 0])
  await ui.unmount()
})

test('the terminal draws the same band with the same buttons', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, headsup: [OLD_RISK] })
  // When
  const ui = await mountBand($, w, 'terminal')
  // Then
  expect(await markdownTexts(ui)).toEqual([...BULLETS, ...ASK_TEXTS])
  for (const key of ['rebuild', `reply-${OLD_ASK.id}`, `dismiss-${OLD_ASK.id}`, 'headsups']) expect(await ui.find({ key })).toBeDefined()
  expect((await ui.find({ key: 'headsups-peek' }))?.text).toBe(`⚠${OLD_RISK.what}`)
  expect((await ui.find({ type: 'Text', text: ' 1 ' }))?.props.backgroundColor).toBe(OLDEST_ASK_COLOR)
  expect((await ui.find({ type: 'Text', text: '⚠' }))?.props.color).toBe(RISK_TEXT)
  // When
  await ui.press({ key: 'headsups' })
  // Then
  expect((await ui.find({ type: 'Markdown', text: /^why:/ }))?.props.text).toBe(`why: ${OLD_RISK.why}`)
  for (const key of ['view-headsups', `reply-headsup-${OLD_RISK.id}`, `ack-${OLD_RISK.id}`]) expect(await ui.find({ key })).toBeDefined()
  // When
  await ui.press({ key: `ack-${OLD_RISK.id}` })
  await w.clock.settle()
  // Then
  expect((await ui.find({ key: `unack-${OLD_RISK.id}` }))?.props.label).toBe('↶')
  await ui.unmount()
})

test('reply puts the ask, quoted, into the prompt box', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  const ui = await mountBand($, w)
  // When
  await ui.press({ key: `reply-${NEW_ASK.id}` })
  // Then
  expect(w.fills).toEqual([`> ${NEW_ASK.text}\n\n`])
  await ui.unmount()
})

test('🗑 saves the verdict in the chat\'s state and leaves a stub with ↶; ↶ takes it back', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  const ui = await mountBand($, w)
  // When
  await ui.press({ key: `dismiss-${OLD_ASK.id}` })
  await w.clock.settle()
  // Then
  expect(w.state.verdicts).toEqual({ [`cta:${OLD_ASK.id}`]: { verdict: 'dismissed', at: NOW_S, turn: MODEL.turn, text: OLD_ASK.text } })
  expect((await ui.find({ key: `undo-${OLD_ASK.id}` }))?.props.label).toBe('↶')
  expect(await ui.find({ key: `reply-${OLD_ASK.id}` })).toBeUndefined()
  expect((await ui.find({ key: 'asks-count' }))?.text).toBe(`📥 ${MODEL.cta.length - 1}`)
  // When
  await ui.press({ key: `undo-${OLD_ASK.id}` })
  await w.clock.settle()
  // Then
  expect(w.state.verdicts).toEqual({})
  expect((await ui.find({ key: `reply-${OLD_ASK.id}` }))?.props.label).toBe('❝')
  await ui.unmount()
})

test('a regenerated dashboard shows up without any action', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  const ui = await mountBand($, w)
  const next = { ...MODEL, turn: 22, last_turn: { bullets: ['Built the band.'], turn: 22 }, cta: [{ id: 'c20', text: 'Try the band?', created_turn: 22 }] }
  // When
  w.state.model = next
  w.state.mtimeMs += 1
  await w.clock.advance(2_000)
  // Then
  expect(await markdownTexts(ui)).toEqual([...next.last_turn.bullets, ...next.cta.map(ask => ask.text)])
  await ui.unmount()
})

test('inline HTML the dashboard agent writes is drawn as formatting, not as tags', { timeoutMs: 20_000 }, async ($, on) => {
  const html = 'Merge <a href="https://github.com/o/r/pull/7">PR 7</a> after <b>CI</b> &amp; <code>make check</code>?'
  const markdown = 'Merge [PR 7](https://github.com/o/r/pull/7) after **CI** & `make check`?'
  const w = world(on, { ...MODEL, cta: [{ id: 'c3', text: html, created_turn: 21 }] })
  // When
  const ui = await mountBand($, w)
  // Then
  expect(await markdownTexts(ui)).toEqual([...BULLETS, markdown])
  await ui.unmount()
})

test('with no open asks the band says nothing is pending', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, cta: [] })
  // When
  const ui = await mountBand($, w)
  // Then
  expect((await ui.find({ type: 'Text', text: /pending/ }))?.text).toBe('✓ Nothing pending')
  await ui.unmount()
})

test('while the first dashboard builds the band says so', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, null)
  w.state.turns = { count: 1, endedAt: NOW_S - 5, prompts: [] }
  w.files[`${CHAT_DIR}/tail-1.json`] = JSON.stringify({ turn: 1, rows: [{ role: 'user', text: 'Start the band.' }] })
  let answer = (_text: string) => {}
  w.answers.push(() => new Promise<string>(resolve => (answer = resolve)))
  // When
  const ui = await mountBand($, w)
  // Then
  expect((await ui.find({ key: 'first-build' }))?.text).toBe("Building this chat's first dashboard…")
  expect((await ui.find({ key: 'status' }))?.props.label).toBe('🔵 0s')
  // When
  answer('<update>{"ops":[{"op":"cta.upsert","text":"Try the band?"}]}</update>')
  await w.clock.advance(2_000)
  // Then
  expect(await ui.find({ key: 'first-build' })).toBeUndefined()
  expect(await markdownTexts(ui)).toEqual(['Try the band?'])
  await ui.unmount()
})

test('the heads-up peek line shows the most severe open heads-up, and the chip counts them all', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, headsup: HEADSUPS })
  // When
  const ui = await mountBand($, w)
  // Then
  expect((await ui.find({ key: 'headsups-peek' }))?.text).toBe(OLD_RISK.what)
  const marker = (await ui.findAll({ type: 'Svg' })).find((svg: { props: { alt: string } }) => svg.props.alt === 'risk')
  expect(marker?.props.source.match(/<path[^>]*fill="([^"]+)"/)?.[1]).toBe(RISK_COLOR)
  expect((await ui.find({ key: 'headsups' }))?.props.label).toBe(`⚠️ ${HEADSUPS.length}`)
  expect(await headsupRows(ui)).toEqual([])
  await ui.unmount()
})

test('the band draws no divider, and only an open view is framed', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, headsup: [FLAG], todo: TODOS })
  const ui = await mountBand($, w)
  const framed = async () => (await ui.findAll({ type: 'Box' })).filter((box: { props: { borderStyle?: string } }) => box.props.borderStyle).map((box: { key?: string }) => box.key)
  // Then
  expect(await ui.findAll({ type: 'Text', text: /^─+$/ })).toEqual([])
  expect(await framed()).toEqual([])
  // When
  await ui.press({ key: 'headsups' })
  // Then
  expect(await framed()).toEqual(['view-headsups'])
  const view = await ui.find({ key: 'view-headsups' })
  // A see-through grey tints the view on a light theme as on a dark one.
  expect([view?.props.backgroundColor, view?.props.borderDimColor, view?.props.paddingX, view?.props.paddingY]).toEqual(['#8080801f', true, 1, 1])
  await ui.unmount()
})

test('a chip opens its view filled, a second chip swaps the view, and the open chip closes it', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, headsup: [FLAG], todo: TODOS })
  const ui = await mountBand($, w)
  const views = async () => (await ui.findAll({ type: 'Box' })).map((box: { key?: string }) => box.key).filter((key?: string) => key?.startsWith('view-') && !key.endsWith('-title'))
  // When
  await ui.press({ key: 'headsups' })
  // Then
  expect(await views()).toEqual(['view-headsups'])
  expect([(await ui.find({ key: 'headsups' }))?.props.variant, (await ui.find({ key: 'todos' }))?.props.dimColor]).toEqual(['primary', true])
  // When
  await ui.press({ key: 'todos' })
  // Then
  expect(await views()).toEqual(['view-todos'])
  expect([(await ui.find({ key: 'headsups' }))?.props.dimColor, (await ui.find({ key: 'todos' }))?.props.variant]).toEqual([true, 'primary'])
  // When
  await ui.press({ key: 'todos' })
  // Then
  expect(await views()).toEqual([])
  await ui.unmount()
})

test('the ⚠️ chip opens the heads-up view: a title row, then every heads-up as a row with its reason, most severe first', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, headsup: HEADSUPS })
  const ui = await mountBand($, w)
  // When
  await ui.press({ key: 'headsups' })
  // Then
  expect((await ui.find({ key: 'view-headsups-title' }))?.text).toBe(`⚠️ Heads-up· ${HEADSUPS.length} open`)
  expect(await headsupRows(ui)).toEqual([`headsup-${OLD_RISK.id}`, `headsup-${NEW_FLAG.id}`, `headsup-${FLAG.id}`])
  const rows = (await ui.findAll({ type: 'Box' })).filter((box: { key?: string }) => box.key?.startsWith('headsup-h'))
  expect(rows.map((row: { props: { alignItems?: string } }) => row.props.alignItems)).toEqual(['flex-start', 'flex-start', 'flex-start'])
  expect(await shownText(ui, `headsup-${OLD_RISK.id}`)).toBe(`${OLD_RISK.what}why: ${OLD_RISK.why}where: ${OLD_RISK.where}18 turns ago❝✓`)
  const metas = (await ui.findAll({ type: 'Markdown', text: /^(where|raised)/ })).map((meta: { props: { text: string } }) => meta.props.text)
  expect(metas).toEqual([`where: ${OLD_RISK.where}`, `where: ${FLAG.where}`])
  const ages = (await ui.findAll({ type: 'Text', text: /^(this turn|.* ago)$/ })).map((text: { text: string }) => text.text)
  expect(ages).toEqual(['18 turns ago', 'this turn', '1 turn ago'])
  const badges = (await ui.findAll({ type: 'Svg' })).filter((badge: { props: { alt: string } }) => ['risk', 'flag'].includes(badge.props.alt))
  expect(badges.map((badge: { props: { alt: string } }) => badge.props.alt)).toEqual(['risk', 'flag', 'flag'])
  expect(badges.map((badge: { props: { source: string } }) => badge.props.source.match(/<path[^>]*fill="([^"]+)"/)?.[1])).toEqual([RISK_COLOR, FLAG_COLOR, FLAG_COLOR])
  expect(await ui.find({ key: 'headsups-peek' })).toBeUndefined()
  // When
  await ui.press({ key: 'headsups' })
  // Then
  expect(await headsupRows(ui)).toEqual([])
  expect(await ui.find({ key: 'headsups-peek' })).toBeDefined()
  await ui.unmount()
})

test('a heads-up or a step stamped later than the chat turn, by an older turn count, shows no age', { timeoutMs: 20_000 }, async ($, on) => {
  const olderCountFlag: Headsup = { ...FLAG, id: 'h9', created_turn: MODEL.turn + 83 }
  const olderCountStep: Todo = { ...OPEN_TODO, id: 't9', created_turn: MODEL.turn + 9 }
  const w = world(on, { ...MODEL, headsup: [olderCountFlag], todo: [olderCountStep] })
  const ui = await mountBand($, w)
  const ages = () => ui.findAll({ type: 'Text', text: /^(this turn|.* ago)$/ })
  // When
  await ui.press({ key: 'headsups' })
  // Then
  expect(await shownText(ui, `headsup-${olderCountFlag.id}`)).toBe(`${olderCountFlag.what.replace(/<\/?b>/g, '**')}why: ${olderCountFlag.why}where: ${olderCountFlag.where}❝✓`)
  expect(await ages()).toEqual([])
  // When
  await ui.press({ key: 'todos' })
  // Then
  expect(await ages()).toEqual([])
  await ui.unmount()
})

test('a heads-up with no place to check and no known turn gets no where-and-when line', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, headsup: [{ ...NEW_FLAG, created_turn: 0 }] })
  const ui = await mountBand($, w)
  // When
  await ui.press({ key: 'headsups' })
  // Then
  expect(await ui.findAll({ type: 'Markdown', text: /^(where|raised)/ })).toEqual([])
  expect((await ui.find({ type: 'Markdown', text: /^why:/ }))?.props.text).toBe(`why: ${NEW_FLAG.why}`)
  await ui.unmount()
})

test('reply puts the heads-up, quoted, into the prompt box as one plain line', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, headsup: HEADSUPS })
  const ui = await mountBand($, w)
  await ui.press({ key: 'headsups' })
  // When
  await ui.press({ key: `reply-headsup-${FLAG.id}` })
  // Then
  expect(w.fills).toEqual([
    `> Dashboard heads-up (flag, raised turn ${FLAG.created_turn}): The band polls the server in every session. Why: ${FLAG.why} Where: ${FLAG.where}\n\n`,
  ])
  await ui.unmount()
})

test('an acknowledged heads-up stays out of the peek line and the count', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, headsup: HEADSUPS })
  w.state.acks = { [OLD_RISK.id]: { ackedAt: 1 } }
  // When
  const ui = await mountBand($, w)
  // Then
  expect((await ui.find({ key: 'headsups-peek' }))?.text).toBe(NEW_FLAG.what)
  expect((await ui.find({ key: 'headsups' }))?.props.label).toBe('⚠️ 2')
  await ui.unmount()
})

test('acknowledged heads-up wait folded behind a count on the title row, and show oldest first with ↶ on request', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, headsup: HEADSUPS })
  w.state.acks = { [FLAG.id]: { ackedAt: 2 }, [OLD_RISK.id]: { ackedAt: 1 } }
  const ui = await mountBand($, w)
  await ui.press({ key: 'headsups' })
  expect(await headsupRows(ui)).toEqual([`headsup-${NEW_FLAG.id}`])
  expect(await ackedRows(ui)).toEqual([])
  expect((await ui.find({ key: 'acked-toggle' }))?.props.label).toBe('▸ 2 acknowledged')
  // When
  await ui.press({ key: 'acked-toggle' })
  // Then
  expect(await ackedRows(ui)).toEqual([`acked-${OLD_RISK.id}`, `acked-${FLAG.id}`])
  expect((await ui.find({ key: `unack-${OLD_RISK.id}` }))?.props.label).toBe('↶')
  expect((await ui.find({ key: 'acked-toggle' }))?.props.label).toBe('▾ 2 acknowledged')
  await ui.unmount()
})

test('✓ moves the heads-up into the open acknowledged group, and ↶ brings it back', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, headsup: HEADSUPS })
  const ui = await mountBand($, w)
  await ui.press({ key: 'headsups' })
  // When
  await ui.press({ key: `ack-${OLD_RISK.id}` })
  await w.clock.settle()
  // Then
  expect(w.state.acks).toEqual({ [OLD_RISK.id]: { ackedAt: NOW_S, turn: MODEL.turn } })
  expect(await headsupRows(ui)).toEqual([`headsup-${NEW_FLAG.id}`, `headsup-${FLAG.id}`])
  expect(await ackedRows(ui)).toEqual([`acked-${OLD_RISK.id}`])
  expect((await ui.find({ key: 'acked-toggle' }))?.props.label).toBe('▾ 1 acknowledged')
  // When
  await ui.press({ key: `unack-${OLD_RISK.id}` })
  await w.clock.settle()
  // Then
  expect(w.state.acks).toEqual({})
  expect(await headsupRows(ui)).toEqual([`headsup-${OLD_RISK.id}`, `headsup-${NEW_FLAG.id}`, `headsup-${FLAG.id}`])
  expect(await ackedRows(ui)).toEqual([])
  await ui.unmount()
})

test('with every heads-up acknowledged, the chip still reaches them, and no peek line shows', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, headsup: HEADSUPS })
  w.state.acks = { [OLD_RISK.id]: { ackedAt: 1 }, [FLAG.id]: { ackedAt: 2 }, [NEW_FLAG.id]: { ackedAt: 3 } }
  // When
  const ui = await mountBand($, w)
  // Then
  expect(await ui.find({ key: 'headsups-peek' })).toBeUndefined()
  expect((await ui.find({ key: 'headsups' }))?.props.label).toBe('⚠️ 0')
  // When
  await ui.press({ key: 'headsups' })
  // Then
  expect((await ui.find({ key: 'view-headsups-title' }))?.text).toBe('⚠️ Heads-up· 0 open▸ 3 acknowledged')
  await ui.unmount()
})

test('a session that never draws the band, such as a headless run, never polls the dashboard', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  // When
  await $.session.start({ cwd: '/w', surface: null, isInteractive: false })
  await w.clock.advance(6_000)
  // Then
  expect(w.reads).toEqual([])
  expect(w.files).toEqual({})
})

test('the band parses the chat\'s state.json again only once it changes, and its ages still move', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  const ui = await mountBand($, w)
  const stateReads = () => w.reads.filter(path => path === `${CHAT_DIR}/state.json`).length
  const before = stateReads()
  // When
  await w.clock.advance(60_000)
  // Then
  expect(stateReads()).toBe(before)
  expect((await ui.find({ key: 'status' }))?.props.label).toBe('🟢 4m')
  // When
  w.state.model = { ...MODEL, turn: 22 }
  w.state.mtimeMs += 1
  await w.clock.advance(2_000)
  // Then
  expect(stateReads()).toBe(before + 1)
  expect((await ui.find({ type: 'Text', text: /· 💬/ }))?.text).toBe('· 💬 22')
  await ui.unmount()
})

test('a band first drawn while a survey holds the slot still starts polling', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  await $.session.start(START.desktop)
  // When
  const ui = await $.ui.mount({ plugin: 'atk-debrief', surface: 'desktop', component: 'AbovePrompt', props: { ...BAND, hasSurvey: true } })
  await w.clock.advance(2_000)
  // Then
  expect(w.reads.filter(path => path === `${CHAT_DIR}/state.json`).length).toBeGreaterThan(1)
  await ui.unmount()
})

test('every press saves in the session: none reaches a server, so the band needs none', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, headsup: HEADSUPS, todo: TODOS })
  w.state.regenErrors = ERRORS
  const ui = await mountBand($, w)
  // When
  for (const [view, keys] of [
    ['asks', [`dismiss-${OLD_ASK.id}`]],
    ['headsups', [`ack-${OLD_RISK.id}`]],
    ['todos', [`check-${ACTIVE_TODO.id}`, `drop-${OPEN_TODO.id}`]],
    ['status', [`dismiss-notice-${TIMEOUT_ERROR.id}`]],
  ] as const) {
    if (view !== 'asks') await ui.press({ key: view })
    for (const key of keys) {
      await ui.press({ key })
      await w.clock.settle()
    }
  }
  // Then
  expect(w.sent).toEqual([])
  expect(w.toasts).toEqual([])
  expect(Object.keys(w.state.verdicts).sort()).toEqual([`cta:${OLD_ASK.id}`, `todo:${ACTIVE_TODO.id}`, `todo:${OPEN_TODO.id}`])
  expect(Object.keys(w.state.acks)).toEqual([OLD_RISK.id])
  expect(w.state.regenErrors.filter(error => error.ackedAt !== null).map(error => error.id)).toEqual([TIMEOUT_ERROR.id])
  await ui.unmount()
})

test('a chat with no dashboard yet says one builds when a turn ends, until its first dashboard lands', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, null)
  // When
  const ui = await mountBand($, w)
  // Then
  expect((await ui.find({ key: 'first-build' }))?.text).toBe('No dashboard yet. It builds when a turn ends.')
  expect(await ui.find({ key: 'status' })).toBeUndefined()
  expect(await ui.find({ key: 'reply-c2' })).toBeUndefined()
  // When
  w.state.model = MODEL
  w.state.mtimeMs += 1
  await w.clock.advance(2_000)
  // Then
  expect(await ui.find({ key: 'first-build' })).toBeUndefined()
  expect(await ui.find({ key: 'reply-c2' })).toBeDefined()
  await ui.unmount()
})

test('▾ at the end of the header folds the band to its header line, and ▸ brings the rest back', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, headsup: HEADSUPS })
  const ui = await mountBand($, w)
  const unfolded = await markdownTexts(ui)
  // When
  await ui.press({ key: 'band-fold' })
  // Then
  expect(await markdownTexts(ui)).toEqual([])
  expect([await ui.find({ key: 'asks' }), await ui.find({ key: 'peeks' })]).toEqual([undefined, undefined])
  expect((await ui.find({ key: 'band-fold' }))?.props.label).toBe('▸')
  // When
  await ui.press({ key: 'band-fold' })
  // Then
  expect(await markdownTexts(ui)).toEqual(unfolded)
  expect(unfolded).toEqual([...BULLETS, ...ASK_TEXTS])
  expect((await ui.find({ key: 'band-fold' }))?.props.label).toBe('▾')
  await ui.unmount()
})

test('a folded header keeps the asks count and every chip', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, headsup: HEADSUPS, links: LINKS, todo: TODOS })
  const ui = await mountBand($, w)
  await ui.press({ key: `dismiss-${OLD_ASK.id}` })
  await w.clock.settle()
  // When
  await ui.press({ key: 'band-fold' })
  // Then
  expect((await ui.find({ key: 'asks-count' }))?.text).toBe(`📥 ${MODEL.cta.length - 1}`)
  for (const key of ['links', 'headsups', 'todos', 'status', 'rebuild']) expect(await ui.find({ key })).toBeDefined()
  await ui.unmount()
})

for (const [chip, view] of [
  ['status', 'view-status'],
  ['links', 'view-links'],
  ['todos', 'view-todos'],
  ['headsups', 'view-headsups'],
] as const) {
  test(`the ${chip} chip on a folded band unfolds it and opens its view`, { timeoutMs: 20_000 }, async ($, on) => {
    const w = world(on, { ...MODEL, links: LINKS, todo: [DONE_TODO], headsup: [OLD_RISK] })
    w.state.acks = { [OLD_RISK.id]: { ackedAt: NOW_S - 60 } }
    const ui = await mountBand($, w)
    await ui.press({ key: chip })
    await ui.press({ key: 'band-fold' })
    // When
    await ui.press({ key: chip })
    // Then
    expect((await ui.find({ key: 'band-fold' }))?.props.label).toBe('▾')
    expect(await ui.find({ key: view })).toBeDefined()
    await ui.unmount()
  })
}

test('the asks follow the last turn with no blank line between', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  // When
  const ui = await mountBand($, w)
  // Then
  expect((await ui.find({ key: 'asks' }))?.props).toEqual({ key: 'asks', flexDirection: 'column', rowGap: 1 })
  await ui.unmount()
})

test('the peek lines, the step in progress and the worst heads-up, sit together below the asks', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, todo: TODOS, headsup: [FLAG] })
  // When
  const ui = await mountBand($, w)
  // Then
  const peeks = await ui.find({ key: 'peeks' })
  expect(peeks?.children.map((child: { props: { key?: string } }) => child.props.key)).toEqual(['todos-peek', 'headsups-peek'])
  await ui.unmount()
})

// A row's text ends with its 🗑.
const DISMISS_LINK_ACTION = '🗑'

test('the header counts the links that have an address, and the chip opens them as a view', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, links: LINKS })
  const ui = await mountBand($, w)
  expect((await ui.find({ key: 'links' }))?.props.label).toBe('🔗 3')
  expect((await ui.find({ key: 'links' }))?.props.dimColor).toBe(true)
  expect(await linkRows(ui)).toEqual([])
  // When
  await ui.press({ key: 'links' })
  // Then
  expect((await ui.find({ key: 'view-links-title' }))?.text).toBe('🔗 Links· 3')
  expect(await linkRows(ui)).toEqual([`link-${ISSUE_LINK.id}`, `link-${PR_LINK.id}`, `link-${NOTEBOOK_LINK.id}`])
  expect((await ui.find({ key: 'links' }))?.props.variant).toBe('primary')
  expect(await markdownTexts(ui)).toEqual([ISSUE_MARKDOWN, PR_MARKDOWN, NOTEBOOK_MARKDOWN, ...BULLETS, ...ASK_TEXTS])
  expect((await ui.find({ key: `link-${ISSUE_LINK.id}` }))?.text).toBe(`🎫${ISSUE_LINK.kind}${ISSUE_MARKDOWN}${DISMISS_LINK_ACTION}`)
  expect((await ui.find({ key: `link-${NOTEBOOK_LINK.id}` }))?.text).toBe(`🔗${NOTEBOOK_LINK.kind}${NOTEBOOK_MARKDOWN}${DISMISS_LINK_ACTION}`)
  // The kind and the link read as one line.
  expect((await ui.find({ key: `kind-link-${ISSUE_LINK.id}` }))?.props.flexDirection).toBe('row')
  expect((await ui.find({ key: `kind-link-${ISSUE_LINK.id}` }))?.text).toBe(`${ISSUE_LINK.kind}${ISSUE_MARKDOWN}`)
  // When
  await ui.press({ key: 'links' })
  // Then
  expect(await linkRows(ui)).toEqual([])
  await ui.unmount()
})

test('🗑 moves the link into the open dismissed group, and ↶ brings it back', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, links: LINKS })
  const ui = await mountBand($, w)
  await ui.press({ key: 'links' })
  expect((await ui.find({ key: `dismiss-${ISSUE_LINK.id}` }))?.props.label).toBe('🗑')
  // When
  await ui.press({ key: `dismiss-${ISSUE_LINK.id}` })
  await w.clock.settle()
  // Then
  expect(w.state.verdicts).toEqual({ [`links:${ISSUE_LINK.id}`]: { verdict: 'dismissed', at: NOW_S, turn: MODEL.turn, text: `${ISSUE_LINK.label} ${ISSUE_LINK.url}` } })
  expect(await linkRows(ui)).toEqual([`link-${PR_LINK.id}`, `link-${NOTEBOOK_LINK.id}`])
  expect(await dismissedLinkRows(ui)).toEqual([`dismissed-link-${ISSUE_LINK.id}`])
  expect((await ui.find({ key: 'dismissed-links-toggle' }))?.props.label).toBe('▾ 1 dismissed')
  expect((await ui.find({ key: 'links' }))?.props.label).toBe('🔗 2')
  // When
  await ui.press({ key: `undismiss-${ISSUE_LINK.id}` })
  await w.clock.settle()
  // Then
  expect(w.state.verdicts).toEqual({})
  expect(await linkRows(ui)).toEqual([`link-${ISSUE_LINK.id}`, `link-${PR_LINK.id}`, `link-${NOTEBOOK_LINK.id}`])
  expect(await dismissedLinkRows(ui)).toEqual([])
  expect((await ui.find({ key: 'links' }))?.props.label).toBe('🔗 3')
  await ui.unmount()
})

test('dismissed links wait folded behind a count on the title row, and show oldest dismissal first with ↶ on request', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, links: LINKS })
  w.state.verdicts = { [`links:${ISSUE_LINK.id}`]: { verdict: 'dismissed', at: 2 }, [`links:${PR_LINK.id}`]: { verdict: 'dismissed', at: 1 } }
  const ui = await mountBand($, w)
  await ui.press({ key: 'links' })
  expect(await linkRows(ui)).toEqual([`link-${NOTEBOOK_LINK.id}`])
  expect(await dismissedLinkRows(ui)).toEqual([])
  expect((await ui.find({ key: 'dismissed-links-toggle' }))?.props.label).toBe('▸ 2 dismissed')
  // When
  await ui.press({ key: 'dismissed-links-toggle' })
  // Then
  expect(await dismissedLinkRows(ui)).toEqual([`dismissed-link-${PR_LINK.id}`, `dismissed-link-${ISSUE_LINK.id}`])
  expect((await ui.find({ key: `undismiss-${PR_LINK.id}` }))?.props.label).toBe('↶')
  expect((await ui.find({ key: 'dismissed-links-toggle' }))?.props.label).toBe('▾ 2 dismissed')
  await ui.unmount()
})

test('a dismiss whose save fails leaves the dismissed group as it was', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, links: LINKS })
  w.state.verdicts = { [`links:${PR_LINK.id}`]: { verdict: 'dismissed', at: 1 } }
  const ui = await mountBand($, w)
  await ui.press({ key: 'links' })
  // When
  w.writeError = 'EACCES: permission denied'
  await ui.press({ key: `dismiss-${ISSUE_LINK.id}` })
  await w.clock.settle()
  // Then
  expect((await ui.find({ key: 'dismissed-links-toggle' }))?.props.label).toBe('▸ 1 dismissed')
  await ui.unmount()
})

test('with every link dismissed the view stays open, ↶ in reach, and folded it says every link is dismissed', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, links: [ISSUE_LINK] })
  const ui = await mountBand($, w)
  await ui.press({ key: 'links' })
  // When
  await ui.press({ key: `dismiss-${ISSUE_LINK.id}` })
  await w.clock.settle()
  // Then
  expect((await ui.find({ key: 'links' }))?.props.label).toBe('🔗 0')
  expect((await ui.find({ key: 'links' }))?.props.variant).toBe('primary')
  expect((await ui.find({ key: `undismiss-${ISSUE_LINK.id}` }))?.props.label).toBe('↶')
  expect(await ui.find({ key: 'links-empty' })).toBeUndefined()
  // When
  await ui.press({ key: 'dismissed-links-toggle' })
  // Then
  expect((await ui.find({ key: 'view-links-title' }))?.text).toBe('🔗 Links· 0▸ 1 dismissed')
  expect((await ui.find({ key: 'links-empty' }))?.text).toBe('✓ Every link dismissed')
  await ui.unmount()
})

test('the phase reads in its theme colour, with the turn beside it dim', { timeoutMs: 20_000 }, async ($, on) => {
  const phaseLooks = {
    planning: ['Planning', ACTIVE_TEXT],
    building: ['Building', GREEN_TEXT],
    blocked: ['Blocked', RISK_TEXT],
    review: ['Awaiting review', FLAG_TEXT],
    shipped: ['Shipped', GREEN_TEXT],
  }
  const w = world(on)
  const ui = await mountBand($, w)
  for (const [phase, [label, color]] of Object.entries(phaseLooks)) {
    // When
    w.state.model = { ...MODEL, phase }
    w.state.mtimeMs += 1
    await w.clock.advance(2_000)
    // Then
    const shown = (await ui.findAll({ type: 'Text' })).filter((text: { text: string }) => text.text === label)
    expect(shown.map((text: { props: { color: string } }) => text.props.color)).toEqual([color])
    expect((await ui.find({ type: 'Text', text: /· 💬/ }))?.props.dimColor).toBe(true)
  }
  await ui.unmount()
})

test('on a folded band no chip reads open, so a press on one opens its view', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  const ui = await mountBand($, w)
  await ui.press({ key: 'status' })
  // When
  await ui.press({ key: 'band-fold' })
  // Then
  expect([(await ui.find({ key: 'status' }))?.props.variant, (await ui.find({ key: 'status' }))?.props.dimColor]).toEqual([undefined, true])
  // When
  await ui.press({ key: 'status' })
  // Then
  expect(await ui.find({ key: 'view-status' })).toBeDefined()
  await ui.unmount()
})

test('a view whose content goes away closes, and stays closed when content comes back', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, links: LINKS })
  const ui = await mountBand($, w)
  await ui.press({ key: 'links' })
  // When
  w.state.model = { ...MODEL, links: [] }
  w.state.mtimeMs += 1
  await w.clock.advance(2_000)
  w.state.model = { ...MODEL, links: LINKS }
  w.state.mtimeMs += 1
  await w.clock.advance(2_000)
  // Then
  expect([await ui.find({ key: 'view-links' }), (await ui.find({ key: 'links' }))?.props.variant]).toEqual([undefined, undefined])
  await ui.unmount()
})

test('the last turn\'s bullets are dots, as ▸ marks a folded part', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  // When
  const ui = await mountBand($, w)
  // Then
  expect((await ui.findAll({ type: 'Text', text: /^▸ $/ })).length).toBe(0)
  expect((await ui.findAll({ type: 'Text', text: /^• $/ })).length).toBe(BULLETS.length)
  await ui.unmount()
})

test('❝ quotes on lines of its own after what the prompt box holds, every line of it', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, cta: [{ ...MODEL.cta[0]!, text: 'First line.\nSecond line.' }] })
  w.draft = 'please check'
  const ui = await mountBand($, w)
  // When
  await ui.press({ key: `reply-${MODEL.cta[0]!.id}` })
  await w.clock.settle()
  // Then
  expect(w.fills).toEqual(['\n\n> First line.\n> Second line.\n\n'])
  await ui.unmount()
})

test('❝ that the prompt box does not take says so', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  w.fillResult = { isFilled: false }
  const ui = await mountBand($, w)
  // When
  await ui.press({ key: `reply-${OLD_ASK.id}` })
  await w.clock.settle()
  // Then
  expect(w.toasts).toEqual(['Not quoted: the prompt box did not take it'])
  await ui.unmount()
})

test('with every heads-up acknowledged, the open view says nothing is open', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, headsup: [FLAG] })
  w.state.acks = { [FLAG.id]: { ackedAt: NOW_S - 60 } }
  const ui = await mountBand($, w)
  // When
  await ui.press({ key: 'headsups' })
  // Then
  expect((await ui.find({ key: 'headsups-empty' }))?.text).toBe('✓ No open heads-up')
  await ui.unmount()
})

test('an acknowledge whose save fails leaves the acknowledged group as it was', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, { ...MODEL, headsup: [FLAG, OLD_RISK] })
  w.state.acks = { [FLAG.id]: { ackedAt: NOW_S - 60 } }
  const ui = await mountBand($, w)
  await ui.press({ key: 'headsups' })
  // When
  w.writeError = 'EACCES: permission denied'
  await ui.press({ key: `ack-${OLD_RISK.id}` })
  await w.clock.settle()
  // Then
  expect((await ui.find({ key: 'acked-toggle' }))?.props.label).toBe('▸ 1 acknowledged')
  await ui.unmount()
})

test('on a narrow band the phase is cut first, then the chips and controls wrap onto more lines, right-aligned, never off the edge', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  // When
  const ui = await mountBand($, w)
  // Then
  const phase = await ui.find({ key: 'header-phase' })
  const controls = await ui.find({ key: 'header-controls' })
  expect([phase?.props.flexShrink, phase?.props.minWidth]).toEqual([100, undefined])
  expect([controls?.props.flexWrap, controls?.props.justifyContent, controls?.props.flexGrow, controls?.props.flexShrink, controls?.props.rowGap]).toEqual([
    'wrap',
    'flex-end',
    1,
    1,
    1,
  ])
  expect([(await ui.find({ key: 'turn' }))?.props.flexShrink, (await ui.find({ key: 'phase-label' }))?.props.minWidth]).toEqual([0, 0])
  await ui.unmount()
})
