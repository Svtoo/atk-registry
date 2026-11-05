import { expect, test } from 'claude-code/testing'
import {
  CHAT_DIR,
  MODEL,
  mountBand,
  NOW_S,
  PANE_PROPS,
  RISK_TEXT,
  SETTINGS_PANE,
  SIGNED_OUT_ERROR,
  type StoredError,
  TIMEOUT_ERROR,
  type Unanswered,
  unmountAll,
  type World,
  world,
  WRITTEN_AGO_S,
} from './world'

const UNKNOWN_MODEL = 'model-1'
const SETTINGS_DESCRIPTION = "The model that rebuilds every chat's dashboard, and how long one rebuild may run."
const SETTINGS_PROPS = { ...PANE_PROPS, title: 'ATK Debrief settings' }
const runCommand = ($: any, command: string) => $.command.run({ command, args: '', origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 100 } })

async function mountSettings($: any, w: World, surface: 'desktop' | 'terminal' = 'desktop') {
  const band = await mountBand($, w, surface)
  await runCommand($, 'debrief-settings')
  await w.clock.settle()
  const pane = await $.ui.mount({ plugin: 'atk-debrief', surface, component: 'Pane', requestId: SETTINGS_PANE, props: SETTINGS_PROPS })
  await w.clock.settle()
  return { band, pane }
}

// The key of the Box that holds the Other model field; a new key draws the field anew, empty.
async function modelIdRowOf(pane: any): Promise<string | undefined> {
  const rowOf = (node: any): string | undefined =>
    node?.children?.some((child: any) => child?.props?.key === 'settings-model-id') ? node.props.key : node?.children?.map(rowOf).find(Boolean)
  return rowOf(await pane.drawn())
}

// The line under a settings field that says what the last change came to.
async function noteLineOf(pane: any, field: 'model' | 'timeout') {
  const [line] = ((await pane.find({ key: `settings-${field}-note` }))?.children ?? []) as { children: string[]; props: { color?: string; dimColor?: boolean } }[]
  return line && { text: line.children.join(''), props: line.props as { color?: string; dimColor?: boolean; wrap?: string } }
}

const noteOf = async (pane: any, field: 'model' | 'timeout') => (await noteLineOf(pane, field))?.text

test('/debrief-settings opens the settings pane with the model and the time limit every chat uses', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, MODEL, { model: 'claude-haiku-5-5', timeoutSeconds: 240 })
  // When
  const { band, pane } = await mountSettings($, w)
  // Then
  expect(w.commands).toEqual(['debrief-settings'])
  expect(w.opened).toEqual([`${SETTINGS_PANE}: ATK Debrief settings (focus)`])
  const model = await pane.find({ key: 'settings-model' })
  expect(model?.props.value).toBe('claude-haiku-5-5')
  // The model in use first, then Claude Code's own families, less its default, plan mode, best and 1M variants.
  expect(model?.props.options.map((option: { value: string }) => option.value)).toEqual(['claude-haiku-5-5', 'sonnet', 'opus', 'haiku', 'fable'])
  expect(model?.props.options[0]?.label).toBe('claude-haiku-5-5 (in use)')
  expect((await pane.find({ key: 'settings-model-id' }))?.props.label).toBe('Other model')
  expect((await pane.find({ key: 'settings-timeout' }))?.props.value).toBe('240')
  expect([await noteOf(pane, 'model'), await noteOf(pane, 'timeout')]).toEqual([undefined, undefined])
  await unmountAll(pane, band)
})

test('a model picked in the settings is saved, and the next rebuild uses it', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  w.files[`${CHAT_DIR}/tail-${MODEL.turn % 3}.json`] = JSON.stringify({ turn: MODEL.turn, rows: [{ role: 'user', text: 'Check.' }] })
  const { band, pane } = await mountSettings($, w)
  // When
  await pane.select({ plugin: 'atk-debrief', key: 'settings-model', value: 'opus' })
  await w.clock.settle()
  // Then
  expect(await noteOf(pane, 'model')).toBe('Saved: the next rebuild uses opus.')
  expect((await pane.find({ key: 'settings-model' }))?.props.value).toBe('opus')
  // When
  await pane.input({ plugin: 'atk-debrief', key: 'settings-timeout', text: '120' })
  await w.clock.settle()
  // Then
  expect([await noteOf(pane, 'model'), await noteOf(pane, 'timeout')]).toEqual(['Saved: the next rebuild uses opus.', 'Saved: a rebuild stops after 120 seconds.'])
  // When
  await band.press({ key: 'rebuild' })
  await w.clock.settle()
  // Then
  expect(w.requests).toHaveLength(2)
  expect([w.requests[0]?.model, w.requests[0]?.maxTokens]).toEqual(['opus', 32_000])
  expect([w.requests[1]?.model, w.requests[1]?.timeoutMs]).toEqual(['opus', 120_000])
  await unmountAll(pane, band)
})

test('a time limit is any whole number of seconds Claude Code takes; another value says so and saves nothing', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  w.files[`${CHAT_DIR}/tail-${MODEL.turn % 3}.json`] = JSON.stringify({ turn: MODEL.turn, rows: [{ role: 'user', text: 'Check.' }] })
  const { band, pane } = await mountSettings($, w)
  for (const text of ['0', '-5', 'soon', '90.5', '2147484']) {
    // When
    await pane.input({ plugin: 'atk-debrief', key: 'settings-timeout', text })
    await w.clock.settle()
    // Then
    const refusal = await noteLineOf(pane, 'timeout')
    expect([refusal?.text, refusal?.props.color, refusal?.props.dimColor]).toEqual(['The time limit is a whole number of seconds, from 1 up to 2147483, the most Claude Code takes.', RISK_TEXT, undefined])
    expect((await pane.find({ key: 'settings-timeout' }))?.props.value).toBe('60')
  }
  // When
  await pane.input({ plugin: 'atk-debrief', key: 'settings-timeout', text: '2147483' })
  await w.clock.settle()
  // Then
  const saved = await noteLineOf(pane, 'timeout')
  expect([saved?.text, saved?.props.color, saved?.props.dimColor]).toEqual(['Saved: a rebuild stops after 2147483 seconds.', undefined, true])
  // When
  await pane.input({ plugin: 'atk-debrief', key: 'settings-timeout', text: ' 5 ' })
  await w.clock.settle()
  await band.press({ key: 'rebuild' })
  await w.clock.settle()
  // Then
  expect(await noteOf(pane, 'timeout')).toBe('Saved: a rebuild stops after 5 seconds.')
  expect(w.requests[0]?.timeoutMs).toBe(5_000)
  await unmountAll(pane, band)
})

test('any other model is entered by its id; a name that is no model id says so', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  const { band, pane } = await mountSettings($, w)
  // When
  await pane.input({ plugin: 'atk-debrief', key: 'settings-model-id', text: 'two words' })
  await w.clock.settle()
  // Then
  expect(await noteOf(pane, 'model')).toBe('A model is a name such as sonnet, or a full id such as claude-haiku-5-5.')
  // When
  await pane.input({ plugin: 'atk-debrief', key: 'settings-model-id', text: 'opus[1m]' })
  await w.clock.settle()
  // Then
  expect(await noteOf(pane, 'model')).toBe('Saved: the next rebuild uses opus[1m].')
  const model = await pane.find({ key: 'settings-model' })
  expect([model?.props.value, model?.props.options[0]?.value]).toEqual(['opus[1m]', 'opus[1m]'])
  await unmountAll(pane, band)
})

test('a model picked from the list draws the Other model field anew, empty', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  const { band, pane } = await mountSettings($, w)
  w.answers.push({ isAnswered: false, reason: 'api-error', error: 'model_not_found', status: 404 })
  await pane.input({ plugin: 'atk-debrief', key: 'settings-model-id', text: UNKNOWN_MODEL })
  await w.clock.settle()
  const before = await modelIdRowOf(pane)
  // When
  await pane.select({ plugin: 'atk-debrief', key: 'settings-model', value: 'opus' })
  await w.clock.settle()
  // Then
  expect([before, await modelIdRowOf(pane)]).toEqual(['settings-model-id-row-0', 'settings-model-id-row-1'])
  expect((await pane.find({ key: 'settings-model-id' }))?.props.value).toBe('')
  await unmountAll(pane, band)
})

test('a model id Claude Code finds no model for is not saved, and stays in its field', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  w.files[`${CHAT_DIR}/tail-${MODEL.turn % 3}.json`] = JSON.stringify({ turn: MODEL.turn, rows: [{ role: 'user', text: 'Check.' }] })
  const { band, pane } = await mountSettings($, w)
  w.answers.push({ isAnswered: false, reason: 'api-error', error: 'model_not_found', status: 404 })
  // When
  await pane.input({ plugin: 'atk-debrief', key: 'settings-model-id', text: UNKNOWN_MODEL })
  await w.clock.settle()
  // Then
  expect(w.requests).toHaveLength(1)
  expect([w.requests[0]?.model, w.requests[0]?.maxTokens]).toEqual([UNKNOWN_MODEL, 32_000])
  const refusal = await noteLineOf(pane, 'model')
  expect([refusal?.text, refusal?.props.color]).toEqual([`Claude Code finds no model ${UNKNOWN_MODEL} for this account. Nothing is saved.`, RISK_TEXT])
  expect(await pane.find({ key: 'settings-model-id' })).toBeDefined()
  expect((await pane.find({ key: 'settings-model' }))?.props.options[0]?.value).toBe('haiku')
  // When
  await band.press({ key: 'rebuild' })
  await w.clock.settle()
  // Then
  expect(w.requests.at(-1)?.model).toBe('haiku')
  await unmountAll(pane, band)
})

test('a picked model shows while it is checked; one Claude Code finds no model for is not saved, and the picker goes back', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  const { band, pane } = await mountSettings($, w)
  let reply: (answer: Unanswered) => void = () => {}
  w.answers.push(() => new Promise(resolve => (reply = resolve)))
  // When
  await pane.select({ plugin: 'atk-debrief', key: 'settings-model', value: 'opus' })
  await w.clock.settle()
  // Then
  expect((await pane.find({ key: 'settings-model' }))?.props.value).toBe('opus')
  const checking = await noteLineOf(pane, 'model')
  expect([checking?.text, checking?.props.dimColor]).toEqual(['Checking opus…', true])
  // When
  reply({ isAnswered: false, reason: 'api-error', error: 'model_not_found', status: 404 })
  await w.clock.settle()
  // Then
  expect((await pane.find({ key: 'settings-model' }))?.props.value).toBe('haiku')
  expect(await noteOf(pane, 'model')).toBe('Claude Code finds no model opus for this account. Nothing is saved.')
  await unmountAll(pane, band)
})

for (const [reply, why] of [
  [{ isAnswered: false, reason: 'api-error', error: 'overloaded', status: 529 }, 'overloaded'],
  [{ isAnswered: false, reason: 'aborted' }, 'no answer in 15 seconds'],
] as const) {
  test(`a picked model that cannot be checked now is saved, and says why: ${why}`, { timeoutMs: 20_000 }, async ($, on) => {
    const w = world(on)
    const { band, pane } = await mountSettings($, w)
    w.answers.push(reply)
    // When
    await pane.select({ plugin: 'atk-debrief', key: 'settings-model', value: 'opus' })
    await w.clock.settle()
    // Then
    expect(w.requests[0]?.timeoutMs).toBe(15_000)
    expect((await pane.find({ key: 'settings-model' }))?.props.value).toBe('opus')
    expect(await noteOf(pane, 'model')).toBe(`Saved: the next rebuild uses opus. It could not be checked now: ${why}.`)
    await unmountAll(pane, band)
  })
}

test('the settings pane wraps its description and its messages at the edge of the pane', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  const { band, pane } = await mountSettings($, w)
  // When
  await pane.input({ plugin: 'atk-debrief', key: 'settings-timeout', text: '120' })
  await w.clock.settle()
  // Then
  expect((await pane.find({ type: 'Text', text: SETTINGS_DESCRIPTION }))?.props.wrap).toBe('wrap')
  expect((await noteLineOf(pane, 'timeout'))?.props.wrap).toBe('wrap')
  await unmountAll(pane, band)
})

const MODEL_DENIED_ERROR: StoredError = {
  ...TIMEOUT_ERROR,
  id: 'err-1799999500-0000000d',
  count: 1,
  code: 'account.model_denied',
  kind: 'model_not_found',
  message: 'the model call failed: model_not_found (HTTP 404)',
}

for (const [name, error, change, saved] of [
  ['a time limit', TIMEOUT_ERROR, { key: 'settings-timeout', text: '300' }, 'Saved: a rebuild stops after 300 seconds.'],
  ['a model', MODEL_DENIED_ERROR, { key: 'settings-model', value: 'opus' }, 'Saved: the next rebuild uses opus.'],
  ['a model for a refused request', { ...MODEL_DENIED_ERROR, code: 'rebuild.refused', kind: 'invalid_request' }, { key: 'settings-model', value: 'sonnet' }, 'Saved: the next rebuild uses sonnet.'],
] as const) {
  test(`${name} saved while this chat shows the problem it fixes rebuilds the chat at once`, { timeoutMs: 20_000 }, async ($, on) => {
    const w = world(on)
    w.state.regenErrors = [error]
    w.files[`${CHAT_DIR}/tail-${MODEL.turn % 3}.json`] = JSON.stringify({ turn: MODEL.turn, rows: [{ role: 'user', text: 'Check.' }] })
    const { band, pane } = await mountSettings($, w)
    // When
    if ('text' in change) await pane.input({ plugin: 'atk-debrief', ...change })
    else await pane.select({ plugin: 'atk-debrief', ...change })
    await w.clock.settle()
    // Then
    expect(await noteOf(pane, change.key === 'settings-timeout' ? 'timeout' : 'model')).toBe(`${saved} This chat rebuilds now.`)
    expect(w.state.regenErrors[0]?.resolvedAt).toBe(w.state.rebuiltAt)
    expect(w.state.rebuiltAt).toBeGreaterThan(NOW_S - WRITTEN_AGO_S)
    await unmountAll(pane, band)
  })
}

test('a setting saved while this chat shows no problem a setting fixes rebuilds nothing', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  w.state.regenErrors = [SIGNED_OUT_ERROR]
  const { band, pane } = await mountSettings($, w)
  // When
  await pane.input({ plugin: 'atk-debrief', key: 'settings-timeout', text: '300' })
  await w.clock.settle()
  // Then
  expect(await noteOf(pane, 'timeout')).toBe('Saved: a rebuild stops after 300 seconds.')
  expect(w.requests).toHaveLength(0)
  await unmountAll(pane, band)
})

test('⚙ on the header, between the status chip and rebuild, opens the settings; the status view has no settings button of its own', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  const ui = await mountBand($, w)
  const keys = (await ui.findAll({ type: 'Button' })).map((button: { key: string }) => button.key)
  expect(keys.slice(keys.indexOf('status'), keys.indexOf('status') + 3)).toEqual(['status', 'settings', 'rebuild'])
  expect((await ui.find({ key: 'settings' }))?.props.label).toBe('⚙')
  // When
  await ui.press({ key: 'settings' })
  await w.clock.settle()
  // Then
  expect(w.opened).toEqual([`${SETTINGS_PANE}: ATK Debrief settings (focus)`])
  // When
  await ui.press({ key: 'status' })
  // Then
  expect((await ui.findAll({ type: 'Button' })).filter((button: { props: { label: string } }) => button.props.label.includes('settings'))).toEqual([])
  await ui.unmount()
})

test('the terminal draws the same settings, with its picker and fields', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  // When
  const { band, pane } = await mountSettings($, w, 'terminal')
  // Then
  for (const key of ['settings-model', 'settings-model-id', 'settings-timeout']) expect(await pane.find({ key })).toBeDefined()
  await unmountAll(pane, band)
})

test('Enter on the model picker without moving keeps the model: the one in use saves nothing', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, MODEL, { model: 'claude-haiku-5-5', timeoutSeconds: 180 })
  w.files[`${CHAT_DIR}/tail-${MODEL.turn % 3}.json`] = JSON.stringify({ turn: MODEL.turn, rows: [{ role: 'user', text: 'Check.' }] })
  const { band, pane } = await mountSettings($, w)
  // When
  const [first] = (await pane.find({ key: 'settings-model' }))?.props.options ?? []
  await pane.select({ plugin: 'atk-debrief', key: 'settings-model', value: first.value })
  await w.clock.settle()
  // Then
  expect(first.value).toBe('claude-haiku-5-5')
  expect(await noteOf(pane, 'model')).toBeUndefined()
  // When
  await pane.input({ plugin: 'atk-debrief', key: 'settings-timeout', text: '120' })
  await w.clock.settle()
  await band.press({ key: 'rebuild' })
  await w.clock.settle()
  // Then
  expect([await noteOf(pane, 'model'), await noteOf(pane, 'timeout')]).toEqual([undefined, 'Saved: a rebuild stops after 120 seconds.'])
  expect([w.requests[0]?.model, w.requests[0]?.timeoutMs]).toEqual(['claude-haiku-5-5', 120_000])
  await unmountAll(pane, band)
})

test('with no model list from Claude Code, the picker offers haiku, sonnet and opus', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  w.configRows = []
  // When
  const { band, pane } = await mountSettings($, w)
  // Then
  expect((await pane.find({ key: 'settings-model' }))?.props.options.map((option: { value: string }) => option.value)).toEqual(['haiku', 'sonnet', 'opus'])
  await unmountAll(pane, band)
})

test('a setting changed in a session that never drew the band leaves it recording nothing', { timeoutMs: 20_000 }, async ($: any, on) => {
  const w = world(on, MODEL, { model: 'claude-haiku-5-5', timeoutSeconds: 180 })
  await runCommand($, 'debrief-settings')
  await w.clock.settle()
  const pane = await $.ui.mount({ plugin: 'atk-debrief', surface: 'desktop', component: 'Pane', requestId: SETTINGS_PANE, props: SETTINGS_PROPS })
  await w.clock.settle()
  const turns = JSON.stringify(w.state.turns)
  // When
  await pane.input({ plugin: 'atk-debrief', key: 'settings-timeout', text: '120' })
  await w.clock.settle()
  await $.prompt.submit({ text: 'Go on.', origin: { kind: 'composer' as const }, wait: false })
  w.messages = [{ role: 'user', text: 'Go on.', toolUses: [] }]
  await $.turn.complete({ answer: 'Done.', durationMs: 1_000, isAborted: false, turnId: 'turn-1', reason: 'answer' } as any)
  await w.clock.settle()
  // Then
  expect([JSON.stringify(w.state.turns), w.requests]).toEqual([turns, []])
  await pane.unmount()
})

test('the model in use typed in Other model says it is saved, not nothing', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on, MODEL, { model: 'claude-haiku-5-5', timeoutSeconds: 180 })
  const { band, pane } = await mountSettings($, w)
  // When
  await pane.input({ plugin: 'atk-debrief', key: 'settings-model-id', text: 'claude-haiku-5-5' })
  await w.clock.settle()
  // Then
  expect(await noteOf(pane, 'model')).toBe('Saved: the next rebuild uses claude-haiku-5-5.')
  await unmountAll(pane, band)
})

test('an empty Other model says what a model is, with no check first', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  const { band, pane } = await mountSettings($, w)
  // When
  await pane.input({ plugin: 'atk-debrief', key: 'settings-model-id', text: '  ' })
  await w.clock.settle()
  // Then
  expect(await noteOf(pane, 'model')).toBe('A model is a name such as sonnet, or a full id such as claude-haiku-5-5.')
  expect(w.requests).toEqual([])
  await unmountAll(pane, band)
})

test('a typed model shows in the picker while it is checked, and a time limit saved meanwhile keeps its own note', { timeoutMs: 20_000 }, async ($, on) => {
  const w = world(on)
  const { band, pane } = await mountSettings($, w)
  let reply: (answer: string) => void = () => {}
  w.answers.push(() => new Promise<string>(resolve => (reply = resolve)))
  // When
  await pane.input({ plugin: 'atk-debrief', key: 'settings-model-id', text: 'claude-opus-5-5' })
  await w.clock.settle()
  await pane.input({ plugin: 'atk-debrief', key: 'settings-timeout', text: '300' })
  await w.clock.settle()
  // Then
  const picker = await pane.find({ key: 'settings-model' })
  expect([picker?.props.value, picker?.props.options.some((option: { value: string }) => option.value === 'claude-opus-5-5')]).toEqual(['claude-opus-5-5', true])
  expect([await noteOf(pane, 'model'), await noteOf(pane, 'timeout')]).toEqual(['Checking claude-opus-5-5…', 'Saved: a rebuild stops after 300 seconds.'])
  // When
  reply('OK')
  await w.clock.settle()
  // Then
  expect(await noteOf(pane, 'model')).toBe('Saved: the next rebuild uses claude-opus-5-5.')
  expect((await pane.find({ key: 'settings-timeout' }))?.props.value).toBe('300')
  await unmountAll(pane, band)
})
