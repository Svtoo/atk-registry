import { expect, test } from 'claude-code/testing'
import {
  ACTIVE_TODO,
  ASK_TEXTS,
  BAND,
  CARDS_MODEL,
  CHAT_DIR,
  DESIGN_CARD,
  HEADSUPS,
  HOME,
  markdownTexts,
  MODEL,
  mountBand,
  mountPane,
  NOW_S,
  OLD_ASK,
  OLD_RISK,
  PROJECT,
  START,
  TIMEOUT_ERROR,
  TODOS,
  unmountAll,
  type World,
  world,
  statusChipOf,
} from './world'

const typed = (text: string) => ({ text, origin: { kind: 'composer' as const }, wait: false })
const turnEnd = (extra: object = {}): any => ({ answer: 'Done.', durationMs: 1_000, isAborted: false, turnId: 'turn-1', reason: 'answer', ...extra })
const userSays = (text: string) => ({ role: 'user' as const, text, toolUses: [] })
const assistantSays = (text: string, toolUses: unknown[] = []) => ({ role: 'assistant' as const, text, toolUses })
const tailOfTurn = (w: World, turn: number) => JSON.parse(w.files[`${CHAT_DIR}/tail-${turn % 3}.json`] ?? 'null')

test('a message the user sends opens a turn; when it ends the mod records it and rebuilds the board with it', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  const ui = await mountBand($, w)
  w.answers.push('<update>{"ops":[{"op":"cta.upsert","text":"Review the band?"},{"op":"last_turn.set","bullets":["Fixed the band."]}]}</update>')
  // When
  await $.prompt.submit(typed('Fix the band.'))
  w.messages = [
    userSays('Earlier prompt'),
    assistantSays('Earlier answer'),
    userSays('Fix the band.'),
    assistantSays('Looking.', [{ tool_use_id: 'u1', tool: 'Bash', input: { command: 'ls' }, text: 'band.tsx' }]),
    { role: 'user', text: '', toolUses: [], toolResults: [{ tool_use_id: 'u1', text: 'band.tsx', isError: false }] },
    assistantSays('Fixed.'),
  ]
  await $.turn.complete(turnEnd())
  await w.clock.settle()
  // Then
  expect(w.state.turns?.count).toBe(MODEL.turn + 1)
  expect(tailOfTurn(w, MODEL.turn + 1)?.rows.map((row: { text: string }) => row.text)).toEqual(['Fix the band.', 'Looking.', '', 'Fixed.'])
  expect(w.requests).toHaveLength(1)
  const [request] = w.requests
  expect(request?.system.startsWith('You keep the dashboard.\n\n<output_format>')).toBe(true)
  expect(request?.prompt).toContain(`<turn n="${MODEL.turn + 1}">\n[USER]\nFix the band.`)
  expect(request?.prompt).toContain("<tool_use name='Bash' id='u1'>")
  expect(request?.prompt).toContain("<tool_result for='u1'>\nband.tsx\n</tool_result>")
  expect([request?.model, request?.timeoutMs]).toEqual(['haiku', 60_000])
  expect(w.state.model?.turn).toBe(MODEL.turn + 1)
  await w.clock.advance(2_000)
  expect(await markdownTexts(ui)).toEqual(['Fixed the band.', ...ASK_TEXTS, 'Review the band?'])
  await ui.unmount()
})

test('after /clear the chat goes on recording and rebuilding: the next drawing catches up again', { timeoutMs: 20_000 }, async ($, on) => {
  // At /clear the engine drops every plugin value and keeps the module loaded; no session.start fires.
  const cleared = { isOn: false, written: new Set<string>() }
  on('state.set', (_s: any, e: any, next: any) => {
    if (cleared.isOn) cleared.written.add(e.key)
    return next(e)
  })
  on('state.get', (_s: any, e: any, next: any) =>
    cleared.isOn && !cleared.written.has(e.key) ? { value: { value: undefined, version: 0 } } : next(e),
  )
  const w = world(on)
  const ui = await mountBand($, w)
  await ui.unmount()
  // When
  cleared.isOn = true
  const after = await $.ui.mount({ plugin: 'atk-debrief', surface: 'desktop', component: 'AbovePrompt', props: BAND })
  await w.clock.settle()
  await w.clock.advance(4_000)
  await $.prompt.submit(typed('After the clear.'))
  w.messages = [userSays('After the clear.'), assistantSays('Done.')]
  await $.turn.complete(turnEnd())
  await w.clock.settle()
  // Then
  expect(w.state.turns?.count).toBe(MODEL.turn + 1)
  expect(w.requests).toHaveLength(1)
  await after.unmount()
})

test('a task notice or a peer\'s message opens no turn; the turn it lands in grows', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  const ui = await mountBand($, w)
  await $.prompt.submit(typed('Run the tests.'))
  w.messages = [userSays('Run the tests.'), assistantSays('Started them.')]
  await $.turn.complete(turnEnd())
  await w.clock.settle()
  // When
  await $.prompt.submit({ text: '<task-notification>tests passed</task-notification>', origin: { kind: 'task-notification' as const }, wait: false })
  w.messages = [...w.messages, userSays('<task-notification>tests passed</task-notification>'), assistantSays('All green.')]
  await $.turn.complete(turnEnd({ turnId: 'turn-2' }))
  await w.clock.settle()
  // Then
  expect(w.state.turns?.count).toBe(MODEL.turn + 1)
  expect(tailOfTurn(w, MODEL.turn + 1)?.rows.map((row: { text: string }) => row.text)).toEqual([
    'Run the tests.',
    'Started them.',
    '<task-notification>tests passed</task-notification>',
    'All green.',
  ])
  expect(w.requests).toHaveLength(2)
  await ui.unmount()
})

test('the tail keeps the last three turns in three files; the prompt reads the newest in full, the two before as prose', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  const ui = await mountBand($, w)
  // When
  for (const n of [1, 2, 3, 4]) {
    await $.prompt.submit(typed(`Step ${n}.`))
    w.messages = [...w.messages, userSays(`Step ${n}.`), assistantSays(`Did ${n}.`, [{ tool_use_id: `u${n}`, tool: 'Read', input: { n }, text: 'x' }])]
    await $.turn.complete(turnEnd({ turnId: `turn-${n}` }))
    await w.clock.settle()
  }
  // Then
  const last = MODEL.turn + 4
  expect(Object.keys(w.files).filter(path => path.includes('/tail-')).sort()).toEqual([0, 1, 2].map(slot => `${CHAT_DIR}/tail-${slot}.json`))
  expect([last - 2, last - 1, last].map(turn => tailOfTurn(w, turn)?.turn)).toEqual([last - 2, last - 1, last])
  const prompt = w.requests.at(-1)?.prompt ?? ''
  expect(prompt).not.toContain('Step 1.')
  expect(prompt).toContain(`<turn n="${last - 1}">\n[USER]\nStep 3.\n\n[ASSISTANT]\nDid 3.\n</turn>`)
  expect(prompt).toContain(`<turn n="${last}">\n[USER]\nStep 4.\n\n[ASSISTANT]\nDid 4.\n<tool_use name='Read' id='u4'>`)
  await ui.unmount()
})

test('a session that never drew the band records nothing and calls no model, until its first draw catches up', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  await $.session.start(START.desktop)
  // When
  await $.prompt.submit(typed('Headless question.'))
  w.messages = [userSays('Headless question.'), assistantSays('Headless answer.')]
  await $.turn.complete(turnEnd())
  await w.clock.settle()
  // Then
  expect(w.files).toEqual({})
  expect(w.requests).toEqual([])
  expect(w.state.turns?.count).toBe(MODEL.turn)
  // When
  const ui = await $.ui.mount({ plugin: 'atk-debrief', surface: 'desktop', component: 'AbovePrompt', props: BAND })
  await w.clock.settle()
  // Then
  expect(w.state.turns?.count).toBe(MODEL.turn + 1)
  expect(w.requests).toHaveLength(1)
  await ui.unmount()
})

test('an interrupted turn is recorded but not rebuilt', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  const ui = await mountBand($, w)
  // When
  await $.prompt.submit(typed('Start something long.'))
  w.messages = [userSays('Start something long.')]
  await $.turn.complete(turnEnd({ isAborted: true, reason: 'aborted' }))
  await w.clock.settle()
  // Then
  expect(w.state.turns?.count).toBe(MODEL.turn + 1)
  expect(w.requests).toEqual([])
  await ui.unmount()
})

test('a rebuild waiting to start reads as just begun, never with an age counted from 1970', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  const ui = await mountBand($, w)
  await $.prompt.submit(typed('Fix the band.'))
  w.messages = [userSays('Fix the band.'), assistantSays('Fixed.')]
  await $.turn.complete(turnEnd())
  // When a press redraws the band before the rebuild the turn asked for has started
  await ui.press({ key: `dismiss-${OLD_ASK.id}` })
  // Then
  expect((await ui.find({ key: 'status' }))?.props.label).toBe('🔵 0s')
  await w.clock.settle()
  await ui.unmount()
})

// What the model is sent back with its answer the dashboard could not use, after the same prompt.
const retryOf = (answer: string, reason: string) =>
  '\n\n# Your previous output was REJECTED. It is below, then the error. Fix the error and re-emit the FULL corrected output: ' +
  'the <update> block with the op-set JSON, then one <freeform ref="…"> block per freeform.upsert.\n' +
  `<previous_output>\n${answer}\n</previous_output>\nError: ${reason}`

test('a rejected answer goes back once with the same prompt, the answer and the reason; a second rejection leaves the board and shows the problem', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  w.files[`${CHAT_DIR}/tail-${MODEL.turn % 3}.json`] = JSON.stringify({ turn: MODEL.turn, rows: [{ role: 'user', text: 'Check.' }] })
  const ui = await mountBand($, w)
  const rejected = 'answer-1 with no blocks'
  w.answers.push(rejected, '<update>{"ops":[{"op":"todo.upsert"}]}</update>')
  // When
  await ui.press({ key: 'rebuild' })
  await w.clock.settle()
  // Then
  expect(w.requests).toHaveLength(2)
  expect(w.requests[1]?.prompt).toBe(`${w.requests[0]?.prompt}${retryOf(rejected, 'no complete <update>…</update> block in the reply')}`)
  expect(w.state.model).toEqual(MODEL)
  expect(w.state.regenErrors.map(error => [error.code, error.count])).toEqual([['rebuild.bad_output', 1]])
  await w.clock.advance(2_000)
  expect((await statusChipOf(ui))[1]).toBe('bad output')
  await ui.press({ key: 'status' })
  expect((await ui.find({ type: 'Text', text: /did not match/ }))?.text).toBe(
    'The answer did not match the shape the dashboard expects, and neither did the corrected answer the model was asked for, so both were thrown ' +
      'away rather than shown half-broken. The dashboard you have is unchanged, and it tries again after your next reply.',
  )
  await ui.press({ key: 'status' })
  // When
  await ui.press({ key: 'rebuild' })
  await w.clock.advance(2_000)
  // Then
  expect(w.state.regenErrors.map(error => error.resolvedAt)).toEqual([NOW_S + 2])
  expect((await ui.find({ key: 'status' }))?.props.label).toBe('🟢 2s')
  await ui.unmount()
})

test('a reply with no text goes back once the same way, and a usable second answer is saved with no problem', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  w.files[`${CHAT_DIR}/tail-${MODEL.turn % 3}.json`] = JSON.stringify({ turn: MODEL.turn, rows: [{ role: 'user', text: 'Check.' }] })
  const ui = await mountBand($, w)
  w.answers.push({ isAnswered: false, reason: 'empty-reply' }, '<update>{"ops":[{"op":"last_turn.set","bullets":["Fixed."]}]}</update>')
  // When
  await ui.press({ key: 'rebuild' })
  await w.clock.settle()
  // Then
  expect(w.requests).toHaveLength(2)
  expect(w.requests[1]?.prompt).toBe(`${w.requests[0]?.prompt}${retryOf('', 'the reply had no text')}`)
  expect(w.state.model?.last_turn.bullets).toEqual(['Fixed.'])
  expect(w.state.regenErrors).toEqual([])
  await ui.unmount()
})

test('a model call refused for a lapsed sign in shows as signed out; one cut short before its time is no problem', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  w.files[`${CHAT_DIR}/tail-${MODEL.turn % 3}.json`] = JSON.stringify({ turn: MODEL.turn, rows: [{ role: 'user', text: 'Check.' }] })
  const ui = await mountBand($, w)
  w.answers.push({ isAnswered: false, reason: 'aborted' }, { isAnswered: false, reason: 'api-error', error: 'authentication_failed', status: 401 })
  // When
  await ui.press({ key: 'rebuild' })
  await w.clock.settle()
  // Then
  expect(w.state.regenErrors).toEqual([])
  // When
  await ui.press({ key: 'rebuild' })
  await w.clock.settle()
  // Then
  expect(w.state.regenErrors.map(error => [error.code, error.kind, error.message])).toEqual([
    ['account.signed_out', 'authentication_failed', 'the model call failed: authentication_failed (HTTP 401)'],
  ])
  expect(w.state.regenErrors[0]?.id).toMatch(/^err-\d{10}-[0-9a-f]{8}$/)
  await ui.unmount()
})

for (const [kind, status] of [['overloaded', 529], ['server_error', 500]] as const) {
  test(`a model too busy to answer (${kind}) is asked again after a wait, not at once`, { timeoutMs: 20_000 }, async ($, on) => {
    const w = world(on)
    w.files[`${CHAT_DIR}/tail-${MODEL.turn % 3}.json`] = JSON.stringify({ turn: MODEL.turn, rows: [{ role: 'user', text: 'Check.' }] })
    const ui = await mountBand($, w)
    w.answers.push({ isAnswered: false, reason: 'api-error', error: kind, status })
    // When
    await ui.press({ key: 'rebuild' })
    await w.clock.settle()
    // Then
    expect(w.requests).toHaveLength(1)
    // When
    await w.clock.advance(5_000)
    // Then
    expect(w.requests).toHaveLength(2)
    expect(w.state.regenErrors).toEqual([])
    expect(w.state.rebuiltAt).toBe(NOW_S + 5)
    await ui.unmount()
  })
}

test('a request the model refuses as invalid names itself, and is not sent again', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  w.files[`${CHAT_DIR}/tail-${MODEL.turn % 3}.json`] = JSON.stringify({ turn: MODEL.turn, rows: [{ role: 'user', text: 'Check.' }] })
  const ui = await mountBand($, w)
  w.answers.push({ isAnswered: false, reason: 'api-error', error: 'invalid_request', status: 400 })
  // When
  await ui.press({ key: 'rebuild' })
  await w.clock.advance(10_000)
  // Then
  expect(w.requests).toHaveLength(1)
  expect(w.state.regenErrors.map(error => [error.code, error.kind])).toEqual([['rebuild.refused', 'invalid_request']])
  expect((await statusChipOf(ui))[1]).toBe('request refused')
  await ui.press({ key: 'status' })
  expect((await ui.find({ type: 'Text', text: /was refused/ }))?.text).toBe('The request this rebuild sent was refused.')
  await ui.unmount()
})

for (const kind of ['account_on_hold', 'verification_required', 'oauth_org_not_allowed', 'cloud_credential_error']) {
  test(`a model call the account may not make (${kind}) shows as an account problem`, { timeoutMs: 20_000 }, async ($, on) => {
    const w = world(on)
    w.files[`${CHAT_DIR}/tail-${MODEL.turn % 3}.json`] = JSON.stringify({ turn: MODEL.turn, rows: [{ role: 'user', text: 'Check.' }] })
    const ui = await mountBand($, w)
    w.answers.push({ isAnswered: false, reason: 'api-error', error: kind, status: 403 })
    // When
    await ui.press({ key: 'rebuild' })
    await w.clock.advance(10_000)
    // Then
    expect(w.requests).toHaveLength(1)
    expect(w.state.regenErrors.map(error => [error.code, error.kind])).toEqual([['account.refused', kind]])
    expect((await statusChipOf(ui))[1]).toBe('account refused')
    await ui.unmount()
  })
}

for (const [name, saved, expected] of [
  ['what the settings pane saved', { model: 'claude-haiku-5-5', timeoutSeconds: 240 }, ['claude-haiku-5-5', 240_000, 32_000]],
  ['with none saved, Haiku for 60 seconds', undefined, ['haiku', 60_000, 32_000]],
  ['with a saved time limit Claude Code would refuse, Haiku for 60 seconds', { model: 'claude-haiku-5-5', timeoutSeconds: 2147484 }, ['haiku', 60_000, 32_000]],
] as const) {
  test(`a rebuild takes its model and time limit from the mod's own store: ${name}`, { timeoutMs: 20_000 }, async ($, on) => {
    const w = world(on, MODEL, saved)
    w.files[`${CHAT_DIR}/tail-${MODEL.turn % 3}.json`] = JSON.stringify({ turn: MODEL.turn, rows: [{ role: 'user', text: 'Check.' }] })
    const ui = await mountBand($, w)
    // When
    await ui.press({ key: 'rebuild' })
    await w.clock.settle()
    // Then
    expect([w.requests[0]?.model, w.requests[0]?.timeoutMs, w.requests[0]?.maxTokens]).toEqual(expected)
    await ui.unmount()
  })
}

const PARENT = 'bbbbbbbb-1111-2222-3333-444444444444'
const PARENT_DIR = `${HOME}/.claude/projects/${PROJECT}/${PARENT}`

async function fingerprintOf(text: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))
  return [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, '0')).join('').slice(0, 12)
}

test('a fork takes the board of the chat it left as it stood at the turn it left, and that chat\'s turn count there', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, null)
  // The parent recorded Step A and Step B as turns 7 and 8, then went on to turn 9.
  const prompts = [`7:${await fingerprintOf('Step A.')}`, `8:${await fingerprintOf('Step B.')}`, `9:${await fingerprintOf('Step C.')}`]
  // Its board holds an ask from turn 3, before the fork, and one from turn 9, after it.
  const parentAsks = [MODEL.cta[0]!, { ...MODEL.cta[1]!, created_turn: 9 }]
  w.files[`${PARENT_DIR}/state.json`] = JSON.stringify({ model: { ...MODEL, turn: 9, cta: parentAsks }, acks: {}, verdicts: {}, turns: { count: 9, endedAt: 1, prompts } })
  w.files[`${PARENT_DIR}/tail-${8 % 3}.json`] = JSON.stringify({ turn: 8, rows: [{ role: 'user', text: 'Step B.' }] })
  w.files[`${PARENT_DIR}/tail-${9 % 3}.json`] = JSON.stringify({ turn: 9, rows: [{ role: 'user', text: 'Step C.' }] })
  const ui = await mountBand($, w)
  // When
  await $.prompt.submit(typed('Try it the other way.'))
  w.messages = [userSays('Step A.'), assistantSays('A done.'), userSays('Step B.'), assistantSays('B done.'), userSays('Try it the other way.'), assistantSays('Trying.')]
  await $.turn.complete(turnEnd())
  await w.clock.settle()
  // Then
  expect(w.state.turns?.count).toBe(9)
  expect(w.state.model?.cta.map(ask => ask.id)).toEqual([MODEL.cta[0]!.id])
  expect(w.state.model?.turn).toBe(9)
  expect(tailOfTurn(w, 8)?.rows).toEqual([{ role: 'user', text: 'Step B.' }])
  expect(tailOfTurn(w, 9)?.rows.map((row: { text: string }) => row.text)).toEqual(['Try it the other way.', 'Trying.'])
  expect(w.requests[0]?.prompt).toContain('<turn n="8">\n[USER]\nStep B.\n</turn>\n<turn n="9">')
  await ui.unmount()
})

test('a fork shows the dashboard of the chat it left as soon as its band draws, before its own first turn', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, null)
  w.state.turns = null
  const prompts = [`7:${await fingerprintOf('Step A.')}`, `8:${await fingerprintOf('Step B.')}`, `9:${await fingerprintOf('Step C.')}`]
  const parentAsks = [MODEL.cta[0]!, { ...MODEL.cta[1]!, created_turn: 9 }]
  w.files[`${PARENT_DIR}/state.json`] = JSON.stringify({ model: { ...MODEL, turn: 9, cta: parentAsks }, acks: {}, verdicts: {}, turns: { count: 9, endedAt: 1, prompts } })
  w.files[`${PARENT_DIR}/tail-${8 % 3}.json`] = JSON.stringify({ turn: 8, rows: [{ role: 'user', text: 'Step B.' }] })
  // The fork holds the chat it left up to Step B.
  w.messages = [userSays('Step A.'), assistantSays('A done.'), userSays('Step B.'), assistantSays('B done.')]
  // When
  const ui = await mountBand($, w)
  // Then
  // The world's turns were set to null above; the first draw sets them again.
  const turns = w.state.turns as { count: number } | null
  expect([turns?.count, w.state.model?.cta.map(ask => ask.id)]).toEqual([8, [MODEL.cta[0]!.id]])
  expect(tailOfTurn(w, 8)?.rows).toEqual([{ role: 'user', text: 'Step B.' }])
  expect([await ui.find({ key: 'first-build' }), (await ui.find({ key: `reply-${MODEL.cta[0]!.id}` }))?.props.label]).toEqual([undefined, '❝'])
  expect(w.requests).toEqual([])
  await ui.unmount()
})

test('a fork is found when its messages differ from the prompts the other chat recorded only in whitespace', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, null)
  w.state.turns = null
  const prompts = [`7:${await fingerprintOf('Step A.')}`, `8:${await fingerprintOf('Step B.')}`]
  w.files[`${PARENT_DIR}/state.json`] = JSON.stringify({ model: { ...MODEL, turn: 8 }, acks: {}, verdicts: {}, turns: { count: 8, endedAt: 1, prompts } })
  w.messages = [userSays('Step A.\n'), assistantSays('A done.'), userSays('Step  B.\n\n'), assistantSays('B done.')]
  // When
  const ui = await mountBand($, w)
  // Then
  const turns = w.state.turns as { count: number } | null
  expect(turns?.count).toBe(8)
  await ui.unmount()
})

test('a chat with earlier messages from no other chat stays as it was at its first draw: nothing is saved for it', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, null)
  w.state.turns = null
  w.messages = [userSays('Something new.'), assistantSays('Sure.')]
  // When
  const ui = await mountBand($, w)
  // Then
  expect([w.state.turns, w.state.model]).toEqual([null, null])
  expect((await ui.find({ key: 'first-build' }))?.text).toBe('No dashboard yet. It builds when a turn ends.')
  await ui.unmount()
})

test('a new chat that shares only one common prompt with another chat is no fork of it', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, null)
  w.files[`${PARENT_DIR}/state.json`] = JSON.stringify({ model: MODEL, turns: { count: 9, endedAt: 1, prompts: [`4:${await fingerprintOf('continue')}`] } })
  const ui = await mountBand($, w)
  // When
  await $.prompt.submit(typed('Now the next part.'))
  w.messages = [userSays('Set up the repo.'), assistantSays('Done.'), userSays('continue'), assistantSays('Done.'), userSays('Now the next part.'), assistantSays('On it.')]
  await $.turn.complete(turnEnd())
  await w.clock.settle()
  // Then
  expect(w.state.turns?.count).toBe(1)
  expect(w.state.model?.cta ?? []).toEqual([])
  await ui.unmount()
})

test('a new chat whose one message is a prompt another chat recorded is no fork of it', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, null)
  w.state.turns = null
  w.files[`${PARENT_DIR}/state.json`] = JSON.stringify({ model: MODEL, turns: { count: 9, endedAt: 1, prompts: [`4:${await fingerprintOf('continue')}`] } })
  w.messages = [userSays('continue')]
  // When
  const ui = await mountBand($, w)
  // Then
  expect(w.state.model ?? null).toBeNull()
  expect(await ui.find({ key: `reply-${MODEL.cta[0]!.id}` })).toBeUndefined()
  await ui.unmount()
})

test('a save that fails says so: no turn or rebuild passes for saved when state.json cannot be written', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  w.files[`${CHAT_DIR}/tail-${MODEL.turn % 3}.json`] = JSON.stringify({ turn: MODEL.turn, rows: [{ role: 'user', text: 'Check.' }] })
  const ui = await mountBand($, w)
  w.writeError = `EACCES: permission denied, open '${CHAT_DIR}/state.json'`
  // When
  await ui.press({ key: 'rebuild' })
  await w.clock.settle()
  // Then
  expect(w.requests).toHaveLength(1)
  expect(w.state.model).toEqual(MODEL)
  // The engine names the call that failed, then the OS's own reason.
  expect(w.toasts).toEqual([`Dashboard not saved: atk-debrief: $.fs.write: ${w.writeError}`])
  // When
  await $.prompt.submit(typed('Go on.'))
  w.messages = [userSays('Go on.'), assistantSays('Going.')]
  await $.turn.complete(turnEnd())
  await w.clock.settle()
  // Then
  expect(w.state.turns?.count).toBe(MODEL.turn)
  expect(w.toasts.at(-1)).toBe(`Dashboard turn not recorded: atk-debrief: $.fs.write: ${w.writeError}`)
  await ui.unmount()
})

test('a turn whose record could not be saved is recorded with the next turn, not lost', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  const ui = await mountBand($, w)
  w.writeError = `EACCES: permission denied, open '${CHAT_DIR}/state.json'`
  await $.prompt.submit(typed('First.'))
  w.messages = [userSays('First.'), assistantSays('One.')]
  await $.turn.complete(turnEnd())
  await w.clock.settle()
  expect(w.state.turns?.count).toBe(MODEL.turn)
  // When
  w.writeError = null
  await $.prompt.submit(typed('Second.'))
  w.messages = [...w.messages, userSays('Second.'), assistantSays('Two.')]
  await $.turn.complete(turnEnd({ turnId: 'turn-2' }))
  await w.clock.settle()
  // Then
  expect(w.state.turns?.count).toBe(MODEL.turn + 2)
  expect(tailOfTurn(w, MODEL.turn + 1)?.rows.map((row: { text: string }) => row.text)).toEqual(['First.', 'One.'])
  expect(tailOfTurn(w, MODEL.turn + 2)?.rows.map((row: { text: string }) => row.text)).toEqual(['Second.', 'Two.'])
  await ui.unmount()
})

test('turns the first draw could not save are recorded with the next turn, not lost', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  await $.session.start(START.desktop)
  await $.prompt.submit(typed('Headless question.'))
  w.messages = [userSays('Headless question.'), assistantSays('Headless answer.')]
  await $.turn.complete(turnEnd())
  w.writeError = `EACCES: permission denied, open '${CHAT_DIR}/state.json'`
  const ui = await $.ui.mount({ plugin: 'atk-debrief', surface: 'desktop', component: 'AbovePrompt', props: BAND })
  await w.clock.settle()
  expect(w.state.turns?.count).toBe(MODEL.turn)
  expect(w.toasts).toEqual([`Dashboard turn not recorded: atk-debrief: $.fs.write: ${w.writeError}`])
  // When
  w.writeError = null
  await $.prompt.submit(typed('Next question.'))
  w.messages = [...w.messages, userSays('Next question.'), assistantSays('Next answer.')]
  await $.turn.complete(turnEnd({ turnId: 'turn-2' }))
  await w.clock.settle()
  // Then
  expect(w.state.turns?.count).toBe(MODEL.turn + 2)
  await ui.unmount()
})

test('a rebuild works for a chat whose turn count is not saved yet: it counts from the board\'s last turn', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  w.state.turns = null
  w.files[`${CHAT_DIR}/tail-${MODEL.turn % 3}.json`] = JSON.stringify({ turn: MODEL.turn, rows: [{ role: 'user', text: 'Check.' }] })
  const ui = await mountBand($, w)
  // When
  await ui.press({ key: 'rebuild' })
  await w.clock.settle()
  // Then
  expect(w.requests).toHaveLength(1)
  expect(w.requests[0]?.prompt).toContain(`<turn n="${MODEL.turn}">\n[USER]\nCheck.`)
  expect(w.toasts).toEqual([])
  await ui.unmount()
})

test('a rebuild press with no turn to read says why nothing happened', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  const ui = await mountBand($, w)
  // When
  await ui.press({ key: 'rebuild' })
  await w.clock.settle()
  // Then
  expect(w.requests).toEqual([])
  expect(w.toasts).toEqual(['Dashboard not rebuilt: no turn of this chat is recorded yet. It rebuilds when your next turn ends.'])
  await ui.unmount()
})

test('each saved rebuild adds to the chat\'s stats, which the status view shows', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, MODEL, { model: 'claude-haiku-5-5', timeoutSeconds: 180 })
  w.files[`${CHAT_DIR}/tail-${MODEL.turn % 3}.json`] = JSON.stringify({ turn: MODEL.turn, rows: [{ role: 'user', text: 'Check.' }] })
  const ui = await mountBand($, w)
  await ui.press({ key: 'status' })
  expect(await ui.find({ key: 'status-stats' })).toBeUndefined()
  // When
  w.answers.push('<update>{"ops":[]}</update>', 'no blocks', '<update>{"ops":[]}</update>')
  await ui.press({ key: 'rebuild' })
  await w.clock.settle()
  await ui.press({ key: 'rebuild' })
  await w.clock.settle()
  // Then
  // Each answer took 2 tokens in, 1 of them from the cache, and 1 out; the second rebuild took two answers.
  expect(w.state.stats).toEqual({ rebuilds: 2, inputTokens: 6, cachedInputTokens: 3, cachedRebuilds: 2, outputTokens: 3, wallMs: 0, models: ['claude-haiku-5-5'] })
  expect((await ui.find({ key: 'status-stats' }))?.text).toBe('2 rebuilds · 6 tokens in, 3 cached, 3 out · avg 0.0s · claude-haiku-5-5')
  await ui.unmount()
})

test('a press whose save fails says so and shows nothing as done', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  const ui = await mountBand($, w)
  w.writeError = 'EACCES: permission denied'
  // When
  await ui.press({ key: `dismiss-${OLD_ASK.id}` })
  await w.clock.settle()
  // Then
  expect(w.toasts).toEqual(['Ask not updated: atk-debrief: $.fs.write: EACCES: permission denied'])
  expect(w.state.verdicts).toEqual({})
  expect((await ui.find({ key: `reply-${OLD_ASK.id}` }))?.props.label).toBe('❝')
  await ui.unmount()
})

test('a press made while a rebuild runs is kept when the rebuild saves', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  w.files[`${CHAT_DIR}/tail-${MODEL.turn % 3}.json`] = JSON.stringify({ turn: MODEL.turn, rows: [{ role: 'user', text: 'Check.' }] })
  let answer = (_text: string) => {}
  w.answers.push(() => new Promise<string>(resolve => (answer = resolve)))
  const ui = await mountBand($, w)
  await ui.press({ key: 'rebuild' })
  await w.clock.settle()
  // When
  await ui.press({ key: `dismiss-${OLD_ASK.id}` })
  await w.clock.settle()
  answer('<update>{"ops":[{"op":"last_turn.set","bullets":["Rebuilt."]}]}</update>')
  await w.clock.advance(2_000)
  // Then
  expect(w.state.model?.last_turn.bullets).toEqual(['Rebuilt.'])
  expect(w.state.verdicts[`cta:${OLD_ASK.id}`]?.verdict).toBe('dismissed')
  expect((await ui.find({ key: `undo-${OLD_ASK.id}` }))?.props.label).toBe('↶')
  await ui.unmount()
})

const withTail = (w: World) => {
  w.files[`${CHAT_DIR}/tail-${MODEL.turn % 3}.json`] = JSON.stringify({ turn: MODEL.turn, rows: [{ role: 'user', text: 'Check.' }] })
}

test('a model call that runs its whole time limit is stopped and shows as took too long', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  withTail(w)
  w.answers.push(async () => {
    await w.clock.sleep(60_000)
    return { isAnswered: false, reason: 'aborted' }
  })
  const ui = await mountBand($, w)
  // When
  await ui.press({ key: 'rebuild' })
  await w.clock.advance(60_000)
  // Then
  expect(w.state.regenErrors.map((error: { code: string; message: string }) => [error.code, error.message])).toEqual([
    ['rebuild.timeout', 'the model call ran past 60s and was stopped'],
  ])
  expect((await statusChipOf(ui))[1]).toBe('took too long')
  await ui.unmount()
})

test('a model still too busy after one wait shows that failure, not a bad answer', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  withTail(w)
  const busy = { isAnswered: false as const, reason: 'api-error', error: 'overloaded', status: 529 }
  w.answers.push(busy, busy, busy)
  const ui = await mountBand($, w)
  // When
  await ui.press({ key: 'rebuild' })
  await w.clock.advance(20_000)
  // Then
  expect(w.requests).toHaveLength(2)
  expect(w.state.regenErrors.map((error: { code: string; kind: string }) => [error.code, error.kind])).toEqual([['rebuild.failed', 'overloaded']])
  await ui.unmount()
})

test('a turn that ends while a rebuild runs gets a rebuild of its own once that one ends', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  withTail(w)
  let answer = (_text: string) => {}
  w.answers.push(() => new Promise<string>(resolve => (answer = resolve)))
  const ui = await mountBand($, w)
  await ui.press({ key: 'rebuild' })
  await w.clock.settle()
  // When
  await $.prompt.submit(typed('Next step.'))
  w.messages = [userSays('Next step.'), assistantSays('Did it.')]
  await $.turn.complete(turnEnd())
  await w.clock.settle()
  answer('<update>{"ops":[]}</update>')
  await w.clock.settle()
  // Then
  expect(w.requests).toHaveLength(2)
  expect(w.requests[1]?.prompt).toContain(`<turn n="${MODEL.turn + 1}">\n[USER]\nNext step.`)
  expect(w.state.model?.turn).toBe(MODEL.turn + 1)
  await ui.unmount()
})

test('two prompts with the same text each get their own turn', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  const ui = await mountBand($, w)
  // When
  w.writeError = 'EACCES: permission denied'
  await $.prompt.submit(typed('continue'))
  w.messages = [userSays('continue'), assistantSays('A.')]
  await $.turn.complete(turnEnd())
  await w.clock.settle()
  w.writeError = null
  await $.prompt.submit(typed('continue'))
  w.messages = [...w.messages, userSays('continue'), assistantSays('B.')]
  await $.turn.complete(turnEnd({ turnId: 'turn-2' }))
  await w.clock.settle()
  // Then
  expect(w.state.turns?.count).toBe(MODEL.turn + 2)
  expect(tailOfTurn(w, MODEL.turn + 1)?.rows.map((row: { text: string }) => row.text)).toEqual(['continue', 'A.'])
  expect(tailOfTurn(w, MODEL.turn + 2)?.rows.map((row: { text: string }) => row.text)).toEqual(['continue', 'B.'])
  await ui.unmount()
})

test('a subagent\'s turn ending records nothing and rebuilds nothing', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  const ui = await mountBand($, w)
  // When
  await $.prompt.submit(typed('Spawn a helper.'))
  w.messages = [userSays('Spawn a helper.')]
  await $.turn.complete(turnEnd({ agentId: 'agent-1' }))
  await w.clock.settle()
  // Then
  expect(w.state.turns?.count).toBe(MODEL.turn)
  expect(w.requests).toEqual([])
  await ui.unmount()
})

for (const [name, view, key, toast] of [
  ['a step checked', 'todos', `check-${ACTIVE_TODO.id}`, 'Step not updated'],
  ['a heads-up acknowledged', 'headsups', `ack-${OLD_RISK.id}`, 'Heads-up not acknowledged'],
  ['a problem dismissed', 'status', `dismiss-notice-${TIMEOUT_ERROR.id}`, 'Problem not dismissed'],
] as const) {
  test(`${name}, whose save fails, says so and saves nothing`, { timeoutMs: 20_000 }, async ($, on) => {
    const w = world(on, { ...MODEL, todo: TODOS, headsup: HEADSUPS })
    w.state.regenErrors = [TIMEOUT_ERROR]
    const ui = await mountBand($, w)
    await ui.press({ key: view })
    const before = JSON.stringify(w.state)
    // When
    w.writeError = 'EACCES: permission denied'
    await ui.press({ key })
    await w.clock.settle()
    // Then
    expect(w.toasts).toEqual([`${toast}: atk-debrief: $.fs.write: EACCES: permission denied`])
    expect(JSON.stringify(w.state)).toBe(before)
    await ui.unmount()
  })
}

test('a card dismissed, whose save fails, says so and saves nothing', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, CARDS_MODEL)
  const { band, pane } = await mountPane($, w)
  // When
  w.writeError = 'EACCES: permission denied'
  await pane.press({ key: `dismiss-${DESIGN_CARD.id}` })
  await w.clock.settle()
  // Then
  expect(w.toasts).toEqual(['Card not updated: atk-debrief: $.fs.write: EACCES: permission denied'])
  expect(w.state.verdicts).toEqual({})
  await unmountAll(pane, band)
})

test('a brief rate limit is asked again after a wait, like a busy model', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  withTail(w)
  w.answers.push({ isAnswered: false, reason: 'api-error', error: 'rate_limit', status: 429 }, '<update>{"ops":[]}</update>')
  const ui = await mountBand($, w)
  // When
  await ui.press({ key: 'rebuild' })
  await w.clock.advance(20_000)
  // Then
  expect(w.requests).toHaveLength(2)
  expect(w.state.regenErrors).toEqual([])
  await ui.unmount()
})

test('a prompt typed over a running turn waits for its own turn, not the turn it was typed over', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  const ui = await mountBand($, w)
  // When
  await $.prompt.submit(typed('Fix the band.'))
  await $.prompt.submit({ ...typed('And the docs.'), turnId: 'turn-1' })
  w.messages = [userSays('Fix the band.'), assistantSays('Fixed.')]
  await $.turn.complete(turnEnd())
  await w.clock.settle()
  // Then
  expect(w.state.turns?.count).toBe(MODEL.turn + 1)
  expect(tailOfTurn(w, MODEL.turn + 1)?.rows.map((row: { text: string }) => row.text)).toEqual(['Fix the band.', 'Fixed.'])
  // When
  w.messages = [...w.messages, userSays('And the docs.'), assistantSays('Docs done.')]
  await $.turn.complete(turnEnd({ turnId: 'turn-2' }))
  await w.clock.settle()
  // Then
  expect(w.state.turns?.count).toBe(MODEL.turn + 2)
  expect(tailOfTurn(w, MODEL.turn + 2)?.rows.map((row: { text: string }) => row.text)).toEqual(['And the docs.', 'Docs done.'])
  await ui.unmount()
})

test('with CLAUDE_CONFIG_DIR set, the mod looks for the chat there, not in ~/.claude', { timeoutMs: 20_000 }, async ($, on) => {
  // The chats are where CLAUDE_CONFIG_DIR says, and a HOME of their own holds none.
  const w = world(on, MODEL, undefined, { HOME: '/home-without-chats', CLAUDE_CONFIG_DIR: `${HOME}/.claude` })
  // When
  const ui = await mountBand($, w)
  // Then
  expect((await statusChipOf(ui))[1]?.startsWith('current')).toBe(true)
  await ui.unmount()
})

test('with CLAUDE_CONFIG_DIR set elsewhere, ~/.claude is not searched', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, MODEL, undefined, { CLAUDE_CONFIG_DIR: '/elsewhere' })
  // When
  const ui = await mountBand($, w)
  // Then
  expect(await ui.find({ key: 'status' })).toBeUndefined()
  await ui.unmount()
})
