import { expect, test } from 'claude-code/testing'

import { bandOf } from '../hooks/band-model'
import { type Io, rebuildChat, readState, recordTurns, saveSettings, setVerdict, settingsOf } from '../hooks/rebuild'
import { forkPointOf, turnsOf } from '../hooks/turns'

// The test runtime has timers; its type library does not name them.
declare const setTimeout: (run: () => void, ms: number) => unknown

const CHAT = { project: 'p', session: 's', dir: '/h/.claude/projects/p/s' }

type Fake = { io: Io; files: Record<string, string>; store: Record<string, unknown>; tornOnce: Set<string>; completes: ((reply: unknown) => void)[]; requests: { timeoutMs: number }[] }

// An Io whose every call yields to the event loop, as the engine's calls do, and whose model calls wait to be answered.
function fakeIo(): Fake {
  const files: Record<string, string> = {}
  const store: Record<string, unknown> = {}
  const tornOnce = new Set<string>()
  const completes: ((reply: unknown) => void)[] = []
  const requests: { timeoutMs: number }[] = []
  const tick = () => new Promise<void>(resolve => setTimeout(resolve, 0))
  let now = 1_000_000_000_000
  const io: Io = {
    pluginRoot: '/root',
    exists: async path => (await tick(), path in files || path === '/root/SYSTEM.md'),
    list: async () => (await tick(), []),
    read: async path => {
      await tick()
      if (path === '/root/SYSTEM.md') return 'sys'
      if (tornOnce.has(path)) {
        tornOnce.delete(path)
        return (files[path] ?? '').slice(0, 10)
      }
      if (!(path in files)) throw new Error('ENOENT')
      return files[path] as string
    },
    write: async (path, text) => {
      await tick()
      files[path] = text
    },
    nowMs: async () => (now += 10),
    sleep: async ms => {
      now += ms
    },
    complete: request => {
      requests.push(request as { timeoutMs: number })
      return new Promise(resolve => completes.push(resolve as (reply: unknown) => void)) as never
    },
    storeGet: async key => (await tick(), store[key]),
    storeSet: async (key, value) => {
      await tick()
      store[key] = value
    },
  }
  return { io, files, store, tornOnce, completes, requests }
}

const BOARD = {
  turn: 5,
  cta: [
    { id: 'c1', text: 'Ask one', created_turn: 1, changed_turn: 1 },
    { id: 'c2', text: 'Ask two', created_turn: 1, changed_turn: 1 },
  ],
  todo: [{ id: 't1', text: 'Step', status: 'active', created_turn: 1, changed_turn: 1 }],
  freeform: [],
  headsup: [],
}

const seed = (f: Fake, extra: object = {}) => {
  f.files[`${CHAT.dir}/state.json`] = JSON.stringify({ model: BOARD, turns: { count: 5, endedAt: 1, prompts: [] }, ...extra })
  f.files[`${CHAT.dir}/tail-2.json`] = JSON.stringify({ turn: 5, rows: [{ role: 'user', text: 'hi' }] })
}

const answered = (text: string) => ({ isAnswered: true, text, usage: { input_tokens: 1, output_tokens: 1 } })
// Waits for the rebuild's next model call, however long the work before it takes on a busy machine.
const nextCall = async (f: Fake) => {
  for (let waited = 0; f.completes.length === 0 && waited < 2_000; waited += 5) await new Promise<void>(resolve => setTimeout(() => resolve(), 5))
}

test('a fork is found only where the new chat\'s earlier prompts line up with the other chat\'s, in order', () => {
  // The same prompt twice counts once, and two common prompts out of order are no fork.
  expect(forkPointOf(['hyes', 'hyes'], ['4:hyes'])).toBeNull()
  expect(forkPointOf(['ha', 'hb'], ['3:hb', '7:ha'])).toBeNull()
  expect(forkPointOf(['ha', 'hb'], ['2:hc', '3:hb', '7:ha'])).toBeNull()
  // A real fork's prompts are the other chat's, in its order, up to the turn it left.
  expect(forkPointOf(['h1', 'h2', 'h3'], ['1:h1', '2:h2', '3:h3', '4:h4'])).toEqual({ turn: 3, shared: 3 })
  // A message that opened no turn there, such as a notice, is passed over, the last one too.
  expect(forkPointOf(['h1', 'hnotice', 'h2'], ['1:h1', '2:h2', '3:h3'])).toEqual({ turn: 2, shared: 2 })
  expect(forkPointOf(['h1', 'h2', 'h3', 'hnotice'], ['1:h1', '2:h2', '3:h3', '4:h4'])).toEqual({ turn: 3, shared: 3 })
  // A turn the other chat recorded from a prompt the messages hold otherwise, such as a slash command, is passed over.
  expect(forkPointOf(['h1', 'hexpanded', 'h3'], ['1:h1', '2:hcommand', '3:h3', '4:h4'])).toEqual({ turn: 3, shared: 2 })
})

test('two presses at once both save', async () => {
  const f = fakeIo()
  seed(f)
  // When
  await Promise.all([setVerdict(f.io, CHAT, 'cta', 'c1', 'dismissed'), setVerdict(f.io, CHAT, 'cta', 'c2', 'dismissed')])
  // Then
  expect(Object.keys((await readState(f.io, CHAT)).verdicts ?? {}).sort()).toEqual(['cta:c1', 'cta:c2'])
})

test('a state.json read while it was being written is read again, not saved over', async () => {
  const f = fakeIo()
  seed(f, { acks: { h9: { ackedAt: 1 } } })
  f.tornOnce.add(`${CHAT.dir}/state.json`)
  // When
  await setVerdict(f.io, CHAT, 'cta', 'c1', 'dismissed')
  // Then
  const state = await readState(f.io, CHAT)
  expect([state.model !== undefined, state.acks?.h9 !== undefined, state.verdicts?.['cta:c1']?.verdict]).toEqual([true, true, 'dismissed'])
})

test('a damaged state.json is kept beside the chat before a save starts it afresh', async () => {
  const f = fakeIo()
  f.files[`${CHAT.dir}/state.json`] = '{"model": {"turn": 5, '
  // When
  await setVerdict(f.io, CHAT, 'cta', 'c1', 'dismissed')
  // Then
  expect(f.files[`${CHAT.dir}/state.json.damaged`]).toBe('{"model": {"turn": 5, ')
  expect((await readState(f.io, CHAT)).verdicts?.['cta:c1']?.verdict).toBe('dismissed')
})

test('an undo pressed while a rebuild runs stays undone when the rebuild saves', async () => {
  const f = fakeIo()
  seed(f, { verdicts: { 'cta:c1': { verdict: 'dismissed', at: 1, turn: 5, text: 'Ask one' } } })
  const running = rebuildChat(f.io, CHAT, { model: 'sonnet', timeoutSeconds: 180 })
  await nextCall(f)
  // When
  await setVerdict(f.io, CHAT, 'cta', 'c1', null)
  f.completes.shift()?.(answered('<update>{"ops":[]}</update>'))
  await running
  // Then
  const state = await readState(f.io, CHAT)
  expect(state.verdicts?.['cta:c1']).toBeUndefined()
  expect((state.model as { cta: { id: string }[] }).cta.map(ask => ask.id)).toEqual(['c1', 'c2'])
})

test('a time limit saved while a new model is checked is kept', async () => {
  const f = fakeIo()
  const picking = saveSettings(f.io, { model: 'opus' })
  await nextCall(f)
  // When
  await saveSettings(f.io, { timeoutSeconds: '300' })
  f.completes.shift()?.(answered('OK'))
  await picking
  // Then
  expect(await settingsOf(f.io)).toEqual({ model: 'opus', timeoutSeconds: 300 })
})

test('the model check asks for as much output as a rebuild, so a model that cannot give it is not saved', async () => {
  const f = fakeIo()
  // When
  const picking = saveSettings(f.io, { model: 'opus' })
  await nextCall(f)
  f.completes.shift()?.(answered('OK'))
  await picking
  // Then
  expect((f.requests[0] as unknown as { maxTokens: number }).maxTokens).toBe(32_000)
})

test('a rebuild and its second try share one time limit', async () => {
  const f = fakeIo()
  seed(f)
  const running = rebuildChat(f.io, CHAT, { model: 'sonnet', timeoutSeconds: 60 })
  await nextCall(f)
  // When
  f.completes.shift()?.(answered('no update here'))
  await nextCall(f)
  f.completes.shift()?.(answered('<update>{"ops":[]}</update>'))
  await running
  // Then
  const [first, second] = f.requests.map(request => request.timeoutMs)
  expect([first, (second ?? 0) < 60_000, (second ?? 0) > 50_000]).toEqual([60_000, true, true])
})

test('a busy model asked again, then a rejected answer, still sends the answer back once with its reason', async () => {
  const f = fakeIo()
  seed(f)
  const running = rebuildChat(f.io, CHAT, { model: 'sonnet', timeoutSeconds: 60 })
  await nextCall(f)
  // When
  f.completes.shift()?.({ isAnswered: false, reason: 'api-error', status: 529, error: 'overloaded', usage: { input_tokens: 0, output_tokens: 0 } })
  await nextCall(f)
  f.completes.shift()?.(answered('no update here'))
  await nextCall(f)
  f.completes.shift()?.(answered('still no update'))
  const result = await running
  // Then
  expect(f.requests).toHaveLength(3)
  expect(result).toEqual({ outcome: 'failed', code: 'rebuild.bad_output' })
  expect((await readState(f.io, CHAT)).regenErrors?.[0]?.message).toBe('the corrected answer was rejected too: no complete <update>…</update> block in the reply')
})

test('a call the engine refuses to send (a blocked model, an output limit) shows as a refused request', async () => {
  const f = fakeIo()
  seed(f)
  f.io.complete = async () => {
    throw new Error('maxTokens 32000 is over the model output limit 8192')
  }
  // When
  const result = await rebuildChat(f.io, CHAT, { model: 'claude-3-5-haiku', timeoutSeconds: 60 })
  // Then
  expect(result).toEqual({ outcome: 'failed', code: 'rebuild.refused' })
  expect((await readState(f.io, CHAT)).regenErrors?.map(error => error.message)).toEqual([
    'Claude Code refused to send the request: maxTokens 32000 is over the model output limit 8192',
  ])
})

const userSays = (text: string) => ({ role: 'user' as const, text, toolUses: [] })
const assistantSays = (text: string) => ({ role: 'assistant' as const, text, toolUses: [] })

test('a prompt the messages do not hold as typed, such as a slash command, starts after the turn before it', () => {
  const messages = [userSays('First.'), assistantSays('One.'), userSays('<command-name>/review</command-name>'), assistantSays('Reviewed.')]
  // When
  const [turn] = turnsOf(messages, ['/review'], 0)
  // Then
  expect(turn?.map(message => message.text)).toEqual(['/review', '<command-name>/review</command-name>', 'Reviewed.'])
})

test('a prompt typed over the running turn and not in its messages yet waits for its own turn', async () => {
  const f = fakeIo()
  seed(f)
  const messages = [userSays('Fix it.'), assistantSays('Fixed.')]
  // When
  const recorded = await recordTurns(f.io, CHAT, [{ text: 'Fix it.', isMidTurn: false }, { text: 'And the docs.', isMidTurn: true }], messages, null)
  // Then
  expect(recorded).toBe(1)
  expect((await readState(f.io, CHAT)).turns?.count).toBe(6)
})

test('a code block too long for one Markdown piece is closed and opened again at each cut', () => {
  const code = Array.from({ length: 700 }, (_, i) => `line ${i} of the listing`).join('\n')
  const body = `## Listing\n\n\`\`\`ts\n${code}\n\`\`\`\n\nAfter the code.`
  const status = { freshness: 'current', label: '', stats: '', notices: [], dismissedNotices: [], resolvedNotices: [] } as never
  // When
  const band = bandOf({ model: { turn: 1, freeform: [{ id: 'f1', body, changed_turn: 1 }] } }, status)
  // Then
  const pieces = band.freeform[0]?.parts.map(part => (part.kind === 'markdown' ? part.text : '')) ?? []
  expect(pieces.length).toBeGreaterThan(1)
  const fenced = pieces.filter(piece => piece.includes('line '))
  expect(fenced.every(piece => piece.startsWith('```ts\n') && (piece.match(/```/g) ?? []).length === 2)).toBe(true)
  expect(pieces.at(-1)).toContain('After the code.')
})

test('a call switched while a rebuild runs is saved as switched', async () => {
  const f = fakeIo()
  seed(f, { verdicts: { 'todo:t1': { verdict: 'done', at: 1, turn: 5, text: 'Step' } } })
  const running = rebuildChat(f.io, CHAT, { model: 'sonnet', timeoutSeconds: 180 })
  await nextCall(f)
  // When
  await setVerdict(f.io, CHAT, 'todo', 't1', null)
  await setVerdict(f.io, CHAT, 'todo', 't1', 'dropped')
  f.completes.shift()?.(answered('<update>{"ops":[]}</update>'))
  await running
  // Then
  const state = await readState(f.io, CHAT)
  expect([(state.model as { todo: { status: string }[] }).todo[0]?.status, state.verdicts?.['todo:t1']?.verdict]).toEqual(['active', 'dropped'])
})

test('a busy model with too little time left to wait for shows as busy, not as out of time', async () => {
  const f = fakeIo()
  seed(f)
  const running = rebuildChat(f.io, CHAT, { model: 'sonnet', timeoutSeconds: 6 })
  await nextCall(f)
  // When
  f.completes.shift()?.({ isAnswered: false, reason: 'api-error', status: 529, error: 'overloaded', usage: { input_tokens: 0, output_tokens: 0 } })
  const result = await running
  // Then
  expect([result, f.requests.length]).toEqual([{ outcome: 'failed', code: 'rebuild.failed' }, 1])
})

test('in a batch, a newest prompt the messages do not hold as typed starts after the prompt before it', () => {
  const messages = [userSays('P0'), assistantSays('r0'), userSays('P1'), assistantSays('r1'), userSays('<command-name>/x</command-name>'), assistantSays('rx')]
  // When
  const turns = turnsOf(messages, ['P1', '/x'], 0)
  // Then
  expect(turns.map(turn => turn.map(message => message.text))).toEqual([
    ['P1', 'r1'],
    ['/x', '<command-name>/x</command-name>', 'rx'],
  ])
})

test('a code block a paragraph leads into, or that text follows at once, is closed and opened again at each cut too', () => {
  const code = Array.from({ length: 900 }, (_, i) => `# step ${i} of the script`).join('\n')
  const body = `## Script\n\nRun this:\n\`\`\`py\n${code}\n\`\`\`\nAfter.`
  const status = { freshness: 'current', label: '', stats: '', notices: [], dismissedNotices: [], resolvedNotices: [] } as never
  // When
  const band = bandOf({ model: { turn: 1, freeform: [{ id: 'f1', body, changed_turn: 1 }] } }, status)
  // Then
  const pieces = band.freeform[0]?.parts.map(part => (part.kind === 'markdown' ? part.text : '')) ?? []
  expect(pieces.length).toBeGreaterThan(1)
  expect(pieces.map(piece => (piece.match(/```/g) ?? []).length % 2)).toEqual(pieces.map(() => 0))
  expect(pieces.slice(1).every(piece => piece.startsWith('```py\n'))).toBe(true)
})

test('a prompt is found in the messages when it differs from them only in whitespace', () => {
  // The engine puts a reminder before the prompt, with one newline more in what the prompt hook gave than in the row.
  const messages = [userSays('<system-reminder>\nForked.\n</system-reminder>\n\nCommit please.'), assistantSays('Committed.')]
  // When
  const [turn] = turnsOf(messages, ['<system-reminder>\nForked.\n</system-reminder>\n\n\nCommit please.'])
  // Then
  expect(turn?.map(message => message.text)).toEqual(['<system-reminder>\nForked.\n</system-reminder>\n\nCommit please.', 'Committed.'])
})
