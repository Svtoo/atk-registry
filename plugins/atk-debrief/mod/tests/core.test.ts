import { expect, test } from 'claude-code/testing'

import { AnswerError, parseAnswer, xmlProblem } from '../hooks/answer'
import { OUTPUT_FORMAT } from '../hooks/answer-format'
import { applyOps, applyVerdicts, boardOf, guardOps, keptBeside, type Update, updateOf, UpdateError } from '../hooks/board'
import { assemblePrompt, capToolBody, digestOf, estimateWords, type TurnRecord } from '../hooks/prompt'
import { modelChoicesOf } from '../hooks/rebuild'
import { codeOfApiError, type RebuildError, statsOf, statusOf, withError } from '../hooks/status'
import { earlierPromptsOf, forkPointOf, isUsersOwn, latestTurnOf, tailOf, tailRecordOf, turnsOf } from '../hooks/turns'

// A board covering every part of the digest, and the digest the model reads for it at turn 13. Its essence is kept
// as a board saved before the essence stood on its own kept it.
const BOARD = {
  phase: 'review',
  turn: 12,
  turn_base: 4,
  seq: 9,
  tldr: { essence: 'Move the rebuild into the mod.', status: '' },
  last_turn: { bullets: ['Ported the prompt.', 'Tests pass.'], turn: 12 },
  links: [
    { id: 'l1', label: 'PR 7', url: 'https://github.com/o/r/pull/7', kind: 'pr', changed_turn: 3 },
    { id: 'l2', label: 'main', url: '', kind: '', changed_turn: 3 },
  ],
  cta: [
    { id: 'c3', text: 'Go on step 2?', created_turn: 10, changed_turn: 11, reason: 'asked' },
    { id: 'c4', text: 'Old ask', created_turn: 0, changed_turn: 0 },
  ],
  todo: [
    { id: 't1', text: 'Port the digest', status: 'done', created_turn: 2, changed_turn: 9, done_turn: 9, reason: 'parity holds' },
    { id: 't2', text: 'Wire the band', status: 'active', created_turn: 5, changed_turn: 5 },
    { id: 't5', text: 'Delete the server', status: 'open', created_turn: 12, changed_turn: 12 },
  ],
  headsup: [
    { id: 'h1', sev: 'risk', what: 'Writes are not atomic', why: 'no rename', where: 'rebuild.ts', created_turn: 4, changed_turn: 8, reason: 'found' },
    { id: 'h2', sev: 'note', what: 'Old row', why: 'history', where: '', created_turn: 0, changed_turn: 0 },
  ],
  freeform: [
    { id: 'f1', body: '## Flow\nprompt -> model -> fold', changed_turn: 6, reason: 'drew it' },
    { id: 'f2', html: '<section><h2>Old</h2></section>', changed_turn: 2 },
    { id: 'f3', body: '## Gone', changed_turn: 3, dismissed_turn: 7 },
  ],
}
const VERDICTS = { 'todo:t2': { verdict: 'done', at: 5, turn: 11, text: 'Wire the band' }, 'cta:c9': { verdict: 'dismissed', at: 6 } }
const ACKS = { h1: { ackedAt: 100, turn: 9 }, h2: {} }
const SERVER_DIGEST = [
  '# Dashboard state — as of conversation turn 12',
  'phase: review',
  'essence (what this chat is about): Move the rebuild into the mod.',
  'last_turn (turn 12): Ported the prompt. | Tests pass.',
  '',
  '## CTA (2) — blockers/questions for the user; remove on resolve',
  '- c3 [created 3t ago, changed 2t ago: asked] Go on step 2?',
  '- c4 [13t ago: ] Old ask',
  '',
  '## Links (2) — the nav chips; upsert by id, remove what stopped mattering',
  '- l1 kind=pr label=PR 7 url=https://github.com/o/r/pull/7',
  '- l2 kind=- label=main url=-',
  '  ⚠ no url, so the chip is hidden from the user: fill the real url via link.upsert, or link.remove it if none exists',
  '',
  '## To-do (3) — full history; done steps are locked and never leave',
  '- t1 done [created 11t ago, done 4t ago: parity holds] Port the digest',
  '- t2 done [created 8t ago, done 2t ago: ] Wire the band',
  '- t5 open [created 1t ago: ] Delete the server',
  '',
  '## Heads-up (2) — FULL list; acked rows are locked; update an open row by id only when its facts clearly changed; never add a duplicate row',
  '- h1 risk [created 9t ago, changed 5t ago: found] what=Writes are not atomic | why=no rename | where=rebuild.ts (acked turn 9, locked)',
  '- h2 flag [13t ago: ] what=Old row | why=history | where=',
  '',
  '## Freeform (2) — sticky reference cards, shown in full; re-upsert a card by id ONLY when the design it shows actually changed, and then change the minimum',
  '- f1 [7t ago: drew it]',
  '## Flow',
  'prompt -> model -> fold',
  '- f2 [11t ago: ]',
  '  ⚠ this card is in the retired HTML format: re-upsert it now as Markdown, each diagram an <svg> block, keeping what it says',
  '<section><h2>Old</h2></section>',
  '',
  '## User verdicts — AUTHORITATIVE clicks by the user, already applied to the state above; never re-add a dropped/dismissed item and never uncheck a user-done one',
  '- user done (turn 11): "Wire the band" (todo t2)',
  '- user dismissed: "(text not recorded)" (cta c9)',
  '',
].join('\n')

const hashOf = (body: string) => `h${body.length}`

test('the digest the model reads holds every part of the board, word for word', () => {
  // When
  const digest = digestOf(applyVerdicts(boardOf(BOARD), VERDICTS), 13, VERDICTS, ACKS)
  // Then
  expect(digest).toBe(SERVER_DIGEST)
})

test('a stored board loads with every field, a card saved as HTML from its html field', () => {
  // When
  const board = boardOf({ turn: 3, freeform: [{ id: 'f1', html: '<section></section>' }] })
  // Then
  expect(board.phase).toBe('planning')
  expect(board.freeform).toEqual([{ id: 'f1', body: '<section></section>', hash: '', changed_turn: 0, dismissed_turn: 0, reason: '' }])
  expect(boardOf(null)).toEqual(boardOf({}))
})

test('an op set folds in: new items get the next ids and this turn, an unknown id is skipped, an unchanged card is no change', () => {
  const board = boardOf(BOARD)
  const update = updateOf({
    phase: 'building',
    essence: 'Move the rebuild and the band into the mod.',
    ops: [
      { op: 'todo.upsert', text: 'Write the tests', status: 'done' },
      { op: 'todo.upsert', id: 't5', status: 'active', reason: 'started' },
      { op: 'cta.upsert', id: 'c99', text: 'nowhere' },
      { op: 'cta.remove', id: 'c4' },
      { op: 'freeform.upsert', id: 'f1', bodyRef: 'same' },
      { op: 'freeform.upsert', bodyRef: 'new', reason: 'a second card' },
      { op: 'last_turn.set', bullets: ['Folded the ops.'] },
    ],
  })
  const bodies = { same: BOARD.freeform[0]?.body ?? '', new: '## New card' }
  const before = { ...board, freeform: board.freeform.map(card => ({ ...card, hash: hashOf(card.body) })) }
  // When
  const after = applyOps(before, update, bodies, 13, hashOf)
  // Then
  expect([after.phase, after.essence, after.turn]).toEqual(['building', 'Move the rebuild and the band into the mod.', 13])
  expect(after.todo.map(t => [t.id, t.status, t.created_turn, t.done_turn])).toEqual([
    ['t1', 'done', 2, 9],
    ['t2', 'active', 5, 0],
    ['t5', 'active', 12, 0],
    ['t10', 'done', 13, 13],
  ])
  expect(after.cta.map(c => c.id)).toEqual(['c3'])
  expect(after.freeform.map(f => [f.id, f.changed_turn])).toEqual([
    ['f1', 6],
    ['f2', 2],
    ['f3', 3],
    ['f11', 13],
  ])
  expect(after.last_turn).toEqual({ bullets: ['Folded the ops.'], turn: 13 })
  expect(board.todo).toHaveLength(3)
})

test('an op set that breaks its schema is refused, naming the problem', () => {
  const refusals = [
    { ops: [{ op: 'todo.upsert', reason: 'no text' }] },
    { ops: [{ op: 'headsup.upsert', sev: 'note', what: 'w', why: 'y' }] },
    { ops: [{ op: 'last_turn.set', bullets: [] }] },
    { ops: [{ op: 'link.upsert', label: 'L', url: 'https://x.test', kind: 'k'.repeat(41) }] },
    { ops: [{ op: 'link.upsert', label: 'A link with no address' }] },
    { ops: [{ op: 'link.upsert', label: 'A link with an empty address', url: '' }] },
    { ops: [{ op: 'link.upsert', id: 'l1', url: '  ' }] },
    { ops: [{ op: 'freeform.upsert', htmlRef: 'x' }] },
    { tldr: { essence: 'x' } },
    { title: 'x' },
    { phase: 'done' },
    { ops: Array(41).fill({ op: 'cta.remove', id: 'c1' }) },
  ]
  for (const data of refusals) expect(() => updateOf(data)).toThrow(UpdateError)
  // An omitted optional field may come as null, and the schema's own spelling of a card's ref is accepted.
  expect(updateOf({ phase: null, ops: [{ op: 'freeform.upsert', body_ref: 'x', id: null }] }).ops).toEqual([{ op: 'freeform.upsert', bodyRef: 'x', reason: '' }])
})

test('the answer is read from its blocks: prose around them is ignored, a card with no block is dropped with a note', () => {
  const raw = [
    'Thinking first.',
    '<update>',
    '{"ops":[{"op":"freeform.upsert","bodyRef":"a"},{"op":"freeform.upsert","bodyRef":"missing"},{"op":"cta.upsert","text":"Ask?"}]}',
    '</update>',
    'between',
    '<freeform ref="a">',
    '## A',
    '<svg viewBox="0 0 4 4"><rect width="2" height="2"/><text>a &amp; b</text></svg>',
    '</freeform>',
    'after',
  ].join('\n')
  // When
  const answer = parseAnswer(raw)
  // Then
  expect(answer.update.ops.map(op => op.op)).toEqual(['freeform.upsert', 'cta.upsert'])
  expect(answer.bodies.a).toBe('## A\n<svg viewBox="0 0 4 4"><rect width="2" height="2"/><text>a &amp; b</text></svg>')
  expect(answer.notes).toEqual(['dropped freeform.upsert ref=missing: no matching <freeform> block'])
})

test('an answer with no closed update block, bad JSON or a diagram that cannot be drawn is rejected', () => {
  const card = (svg: string) => `<update>{"ops":[{"op":"freeform.upsert","bodyRef":"x"}]}</update>\n<freeform ref="x">\n## X\n${svg}\n</freeform>`
  for (const raw of ['no blocks', '<update>{"ops":[]}', '<update>{ops: []}</update>', card('<svg><g></svg>'), card('<svg onload="x()"></svg>'), card('<svg><rect/>')]) {
    expect(() => parseAnswer(raw)).toThrow(AnswerError)
  }
})

const DISMISSED_LINK_URL = 'https://example.com/pull/1'
const LOCK_BOARD = boardOf({
  turn: 20,
  seq: 30,
  links: [
    { id: 'l1', label: 'Dismissed link', url: DISMISSED_LINK_URL, kind: 'pr' },
    { id: 'l2', label: 'Live link', url: 'https://example.com/doc/2', kind: 'doc' },
  ],
  todo: [
    { id: 't1', text: 'Done step', status: 'done', created_turn: 1, changed_turn: 5, done_turn: 5 },
    { id: 't2', text: 'Open step', status: 'open', created_turn: 2, changed_turn: 2 },
    { id: 't3', text: 'Another open step', status: 'open', created_turn: 2, changed_turn: 2 },
  ],
  cta: [{ id: 'c1', text: 'Go on?', created_turn: 3, changed_turn: 3 }],
  headsup: [
    { id: 'h1', sev: 'risk', what: 'Acked row', why: 'seen', where: '', created_turn: 4, changed_turn: 4 },
    { id: 'h2', sev: 'flag', what: 'Open row', why: 'unseen', where: '', created_turn: 4, changed_turn: 4 },
  ],
  freeform: [{ id: 'f1', body: '## Gone', hash: 'a', changed_turn: 1, dismissed_turn: 6 }],
})
const guarded = (ops: unknown[], verdicts: Record<string, { verdict: string; text?: string }> = {}) =>
  guardOps(LOCK_BOARD, { ops } as Update, { h1: { ackedAt: 100, turn: 9 } }, verdicts)

test('the model cannot change what is locked: a done to-do, an acknowledged heads-up, a dismissed card', () => {
  const result = guarded([
    { op: 'todo.upsert', id: 't1', text: 'Rewritten', reason: 'r' },
    { op: 'todo.upsert', id: 't1', status: 'open', reason: 'r' },
    { op: 'todo.remove', id: 't1', reason: 'r' },
    { op: 'headsup.upsert', id: 'h1', what: 'Rewritten', reason: 'r' },
    { op: 'headsup.remove', id: 'h1', reason: 'r' },
    { op: 'freeform.upsert', id: 'f1', bodyRef: 'x', reason: 'r' },
  ])
  expect([result.update.ops, result.ignored, result.repairs]).toEqual([[], 6, 0])
})

test('a dismissed link is locked: the model cannot change or remove it, nor add its address as a new link', () => {
  const liveRename = { op: 'link.upsert', id: 'l2', label: 'Live link, renamed', reason: 'r' }
  const result = guarded(
    [
      { op: 'link.upsert', id: 'l1', label: 'Rewritten', reason: 'r' },
      { op: 'link.remove', id: 'l1', reason: 'r' },
      { op: 'link.upsert', label: 'Same address, new link', url: DISMISSED_LINK_URL, kind: 'pr', reason: 'r' },
      liveRename,
    ],
    { 'links:l1': { verdict: 'dismissed' } },
  )
  expect([result.update.ops, result.ignored]).toEqual([[liveRename], 3])
})

test('a to-do the user checked is locked before a rebuild takes the check in', () => {
  const result = guarded([{ op: 'todo.upsert', id: 't2', text: 'Rewritten', reason: 'r' }], { 'todo:t2': { verdict: 'done' } })
  expect([result.update.ops, result.ignored]).toEqual([[], 1])
})

test('open items carry no limit: every rewrite and removal passes, so a turn can act on whatever the user just said', () => {
  const ops = [
    { op: 'todo.upsert', id: 't2', text: 'Rewritten', reason: 'r' },
    { op: 'todo.remove', id: 't3', reason: 'r' },
    { op: 'headsup.upsert', id: 'h2', what: 'Rewritten', reason: 'r' },
    { op: 'headsup.remove', id: 'h2', reason: 'r' },
    { op: 'cta.upsert', id: 'c1', text: 'Reworded?', reason: 'r' },
  ]
  const result = guarded(ops)
  expect([result.update.ops, result.ignored, result.repairs]).toEqual([ops, 0, 5])
})

test('progress is no repair: a status change, a resolved ask and a new item are not counted as one', () => {
  const ops = [
    { op: 'todo.upsert', id: 't2', status: 'done', reason: 'r' },
    { op: 'cta.remove', id: 'c1', reason: 'r' },
    { op: 'todo.upsert', text: 'A new step', reason: 'r' },
    { op: 'headsup.upsert', sev: 'flag', what: 'A new row', why: 'y', reason: 'r' },
  ]
  const result = guarded(ops)
  expect([result.update.ops, result.ignored, result.repairs]).toEqual([ops, 0, 0])
})

test('an upsert that changes nothing is dropped, so a stable item keeps its stamps', () => {
  const result = guarded([
    { op: 'todo.upsert', id: 't2', text: 'open  STEP', reason: 'r' },
    { op: 'cta.upsert', id: 'c1', text: 'Go on?', reason: 'r' },
    { op: 'headsup.upsert', id: 'h2', what: 'Open row', reason: 'r' },
  ])
  expect([result.update.ops, result.ignored, result.repairs]).toEqual([[], 0, 0])
})

test('a dropped step or a dismissed ask can come back: the user may ask for it in the chat', () => {
  const verdicts = { 'todo:t9': { verdict: 'dropped', text: 'Old step' }, 'cta:c9': { verdict: 'dismissed', text: 'Old ask?' } }
  const ops = [{ op: 'todo.upsert', text: 'Old step', reason: 'r' }, { op: 'cta.upsert', text: 'Old ask?', reason: 'r' }]
  const result = guarded(ops, verdicts)
  expect([result.update.ops, result.ignored]).toEqual([ops, 0])
})

test('an open to-do and an open heads-up can be removed, with a reason', () => {
  const update = updateOf({ ops: [{ op: 'todo.remove', id: 't2', reason: 'never a plan step' }, { op: 'headsup.remove', id: 'h2', reason: 'proved wrong' }] })
  // When
  const board = applyOps(LOCK_BOARD, update, {}, 21, () => '')
  // Then
  expect(board.todo.map(it => it.id)).toEqual(['t1', 't3'])
  expect(board.headsup.map(it => it.id)).toEqual(['h1'])
  expect(() => updateOf({ ops: [{ op: 'todo.remove', id: 't2' }] })).toThrow(UpdateError)
})

test('the task keeps items stable by default', () => {
  const { user } = assemblePrompt({ board: boardOf({}), turns: [], turn: 1, systemTemplate: '', verdicts: {}, acks: {} })
  expect(user).toContain('Items are stable by default')
  expect(user).toContain('or the user asks for the change')
  expect(user).not.toContain('repairs are open')
  expect(user).not.toContain('get consolidated, rewritten, or removed')
})

test('reasoning before the blocks that names the update or a card block changes nothing that is read', () => {
  const raw = [
    'I will re-upsert the card with a <freeform ref="install"> block, after an <update> that closes with </update>.',
    '<update>',
    '{"ops":[{"op":"freeform.upsert","bodyRef":"install"}]}',
    '</update>',
    '<freeform ref="install">',
    '## Install path',
    '',
    'Run install.',
    '</freeform>',
  ].join('\n')
  // When
  const answer = parseAnswer(raw)
  // Then
  expect(answer.update.ops.map(op => op.op)).toEqual(['freeform.upsert'])
  expect(answer.bodies).toEqual({ install: '## Install path\n\nRun install.' })
  expect(answer.notes).toEqual([])
})

test('a diagram is well-formed XML: tags close in order, values are quoted, entities are XML\'s own', () => {
  expect(xmlProblem('<svg><!-- c --><style><![CDATA[ a > b ]]></style><text x="1">a &lt; b &#169;</text></svg>')).toBeNull()
  expect(xmlProblem('<svg><text>a > b</text></svg>')).toBeNull()
  for (const bad of ['<svg><g></svg>', '<svg width=10></svg>', '<svg><text>a&nbsp;b</text></svg>', '<svg><text>a & b</text></svg>', '<svg x="1" x="2"></svg>', '<svg/><svg/>']) {
    expect(xmlProblem(bad)).not.toBeNull()
  }
})

test('the user\'s verdicts apply to the board, and stay beside it until the board carries them', () => {
  const board = applyVerdicts(boardOf(BOARD), { 'todo:t5': { verdict: 'dropped' }, 'freeform:f1': { verdict: 'dismissed', turn: 12 } })
  expect(board.todo.map(t => t.id)).toEqual(['t1', 't2'])
  expect(board.freeform[0]?.dismissed_turn).toBe(12)
  // When
  const kept = keptBeside(board, ACKS, { 'todo:t1': { verdict: 'done', at: 1 }, 'todo:t5': { verdict: 'dropped', at: 2 }, 'freeform:f1': { verdict: 'dismissed', at: 3 } })
  // Then
  expect(kept.verdicts).toEqual({ 'todo:t5': { verdict: 'dropped', at: 2 } })
  expect(kept.acks).toEqual(ACKS)
})

test('a dismissed link\'s verdict stays beside the board while the link lives, past any count of newer verdicts, and goes with it', () => {
  const board = boardOf({ links: [{ id: 'l1', label: 'Dismissed link', url: DISMISSED_LINK_URL, kind: 'pr' }] })
  const dismissal = { verdict: 'dismissed', at: 1 }
  const newer = Object.fromEntries(Array.from({ length: 50 }, (_, n) => [`cta:c${n}`, { verdict: 'dismissed', at: 10 + n }]))
  // When
  const kept = keptBeside(board, {}, { 'links:l1': dismissal, 'links:l9': { verdict: 'dismissed', at: 2 }, ...newer })
  // Then
  expect(kept.verdicts).toEqual({ 'links:l1': dismissal, ...newer })
})

const rowOfText = (role: 'user' | 'assistant', text: string) => ({ role, text })

test('the prompt holds the board, the newest turn in full and the two before it as prose', () => {
  const turns: TurnRecord[] = [10, 11, 12, 13].map(turn => ({
    turn,
    rows: [
      rowOfText('user', `Prompt ${turn}`),
      { role: 'assistant', text: `Answer ${turn}`, toolUses: [{ id: `u${turn}`, name: 'Bash', input: { command: 'ls' } }] },
      { role: 'user', text: '', toolResults: [{ id: `u${turn}`, text: `out ${turn}` }] },
    ],
  }))
  // When
  const prompt = assemblePrompt({ board: boardOf(BOARD), turns, turn: 13, systemTemplate: 'You keep the dashboard.\n', verdicts: {}, acks: {} })
  // Then
  expect(prompt.system.startsWith('You keep the dashboard.\n\n<output_format>')).toBe(true)
  expect(prompt.user).toContain('<dashboard_state turn="13">\n# Dashboard state — as of conversation turn 12')
  expect(prompt.user).not.toContain('Prompt 10')
  expect(prompt.user).toContain('<turn n="11">\n[USER]\nPrompt 11\n\n[ASSISTANT]\nAnswer 11\n</turn>')
  expect(prompt.user).toContain(
    "<turn n=\"13\">\n[USER]\nPrompt 13\n\n[ASSISTANT]\nAnswer 13\n<tool_use name='Bash' id='u13'>\n{\n  \"command\": \"ls\"\n}\n</tool_use>\n\n[USER]\n<tool_result for='u13'>\nout 13\n</tool_result>\n</turn>",
  )
  expect(prompt.user.endsWith('Never create a duplicate of an item already listed — update it by id.\n</task>\n')).toBe(true)
  expect(prompt.isTruncated).toBe(false)
})

test('a newest turn too long for the prompt has its tool output cut, never the turn', () => {
  const long = Array.from({ length: 120_000 }, (_, i) => `w${i % 10}`).join(' ')
  const turns: TurnRecord[] = [{ turn: 1, rows: [rowOfText('user', 'Read the log.'), { role: 'user', text: '', toolResults: [{ id: 'u1', text: long }] }] }]
  // When
  const prompt = assemblePrompt({ board: boardOf({}), turns, turn: 1, systemTemplate: '', verdicts: {}, acks: {} })
  // Then
  // The cap holds the tool output to the budget; the turn's own words and tags come on top, as on the server.
  expect(estimateWords(long)).toBe(120_000)
  expect(prompt.isTruncated).toBe(true)
  expect(prompt.transcriptWords).toBeLessThan(100_100)
  expect(prompt.user).toContain('Read the log.')
  expect(prompt.user).toContain('words truncated — see the tool call in the chat for the full output')
  expect(capToolBody('short body', 100)).toBe('short body')
  expect(estimateWords('one two, three')).toBe(4)
})

test('a newest turn whose tool inputs and prose are too long still fits the transcript budget', () => {
  const words = (count: number) => Array.from({ length: count }, (_, i) => `w${i % 10}`).join(' ')
  const writes = Array.from({ length: 30 }, (_, i) => ({ id: `u${i}`, name: 'Write', input: { file_path: `f${i}.ts`, content: words(7_000) } }))
  const turns: TurnRecord[] = [
    { turn: 1, rows: [rowOfText('user', 'Write the files.'), { role: 'assistant', text: words(50_000), toolUses: writes }] },
  ]
  // When
  const prompt = assemblePrompt({ board: boardOf({}), turns, turn: 1, systemTemplate: '', verdicts: {}, acks: {} })
  // Then
  expect(prompt.isTruncated).toBe(true)
  expect(prompt.transcriptWords).toBeLessThan(100_100)
  expect(estimateWords(prompt.user)).toBeLessThan(110_000)
  expect(prompt.user).toContain('Write the files.')
})

const message = (role: 'user' | 'assistant', text: string, extra: object = {}) => ({ role, text, toolUses: [], ...extra })

test('a message the user sends opens a turn; a notice, a peer or another plugin does not', () => {
  expect(['composer', 'bridge', 'sdk', 'slack-ping'].map(kind => isUsersOwn({ kind } as never))).toEqual([true, true, true, true])
  expect(['task-notification', 'peer', 'scheduled-trigger', 'unclassified'].map(kind => isUsersOwn({ kind } as never))).toEqual([false, false, false, false])
  expect(isUsersOwn({ kind: 'plugin', name: 'x', asUser: true } as never)).toBe(true)
  expect(isUsersOwn({ kind: 'plugin', name: 'x' } as never)).toBe(false)
})

test('turns are cut at each prompt; a prompt sent twice finds its latest copy; a prompt a compaction dropped keeps its text', () => {
  const messages = [
    message('user', 'Summary of earlier work'),
    message('user', 'go'),
    message('assistant', 'first'),
    message('user', 'go'),
    message('assistant', 'second'),
    message('user', 'and this'),
    message('assistant', 'third'),
  ]
  // When
  const cut = turnsOf(messages, ['go', 'and this'])
  // Then
  expect(cut.map(rows => rows.map(row => row.text))).toEqual([
    ['go', 'second'],
    ['and this', 'third'],
  ])
  expect(turnsOf(messages, ['lost one', 'and this']).map(rows => rows.map(row => row.text))).toEqual([['lost one'], ['and this', 'third']])
  expect(latestTurnOf([...messages, message('user', '<task-notification>done</task-notification>'), message('assistant', 'noted')], 'and this')?.map(row => row.text)).toEqual([
    'and this',
    'third',
    '<task-notification>done</task-notification>',
    'noted',
  ])
})

test('a tail file holds its turn; a file holding another turn, or damaged, is not read as this one', () => {
  const record = tailOf(5, [message('user', 'Fix it.'), message('assistant', 'Fixed.', { toolUses: [{ tool_use_id: 'u1', tool: 'Edit', input: { file: 'a.ts' }, result: { big: 'x' } }] })])
  expect(record.rows[1]).toEqual({ role: 'assistant', text: 'Fixed.', toolUses: [{ id: 'u1', name: 'Edit', input: { file: 'a.ts' } }] })
  expect(tailRecordOf(JSON.stringify(record), 5)).toEqual(record)
  expect(tailRecordOf(JSON.stringify(record), 8)).toBeNull()
  expect(tailRecordOf('{"turn": 5, "rows": [', 5)).toBeNull()
})

// UTF-8 bytes of a text, as the engine counts a file it writes.
const bytesOf = (text: string) => [...text].reduce((sum, char) => sum + ((char.codePointAt(0) ?? 0) < 0x80 ? 1 : (char.codePointAt(0) ?? 0) < 0x800 ? 2 : (char.codePointAt(0) ?? 0) < 0x10000 ? 3 : 4), 0)

test('a tail file stays under the 4 MiB the engine writes, counted in bytes, however large its turn', () => {
  const output = 'ж'.repeat(25_000)
  const rows = [
    message('user', 'Read every log.'),
    ...Array.from({ length: 220 }, (_, i) => message('user', '', { toolResults: [{ tool_use_id: `u${i}`, text: output }] })),
    message('assistant', 'Read them all.'),
  ]
  // When
  const record = tailOf(7, rows)
  // Then
  expect(bytesOf(JSON.stringify(record))).toBeLessThan(4 * 1024 * 1024)
  expect(record.turn).toBe(7)
  expect(record.rows[0]?.text).toBe('Read every log.')
  expect(record.rows.at(-1)?.text).toBe('Read them all.')
})

test('a rate limit that outlasts its retry says what is known: a limit, short or the usage limit, and nothing lost', () => {
  const errors: RebuildError[] = [{ id: 'err-1', at: 1, lastAt: 1, count: 1, code: codeOfApiError('rate_limit'), kind: 'rate_limit', message: 'the model call failed: rate_limit (HTTP 429)', ackedAt: null, resolvedAt: null }]
  // When
  const status = statusOf({ errors, rebuiltAt: 1, runningSince: null, unbuiltTurns: 0, stats: null } as never, 100)
  // Then
  const notice = status.notices[0]
  expect([notice?.severity, notice?.title]).toEqual(['degraded', 'Claude is limiting requests, so this rebuild did not run.'])
  expect(notice?.what).toContain('a short rate limit or your usage limit')
  expect(status.label).toBe('rate limited')
})

test('a repeat of an open problem counts up; the chip names the newest and how many are open', () => {
  let errors: RebuildError[] = []
  const add = (code: string, at: number) => (errors = withError(errors, { code, kind: 'k', message: 'm' }, at, () => `err-${at}-00000000`))
  add('rebuild.timeout', 100)
  add('rebuild.timeout', 200)
  add('account.signed_out', 300)
  expect(errors.map(e => [e.code, e.count, e.at, e.lastAt])).toEqual([
    ['rebuild.timeout', 2, 100, 200],
    ['account.signed_out', 1, 300, 300],
  ])
  const facts = { runningSince: null, rebuiltAt: 50, unbuiltTurns: 0, errors }
  expect(statusOf(facts, 400).label).toBe('2 × signed out')
  expect(statusOf({ ...facts, errors: [] }, 400).label).toBe('current · 5m')
  expect(statusOf({ ...facts, errors: [], unbuiltTurns: 1 }, 400).label).toBe('behind 1 turn')
  expect(statusOf({ ...facts, errors: [], unbuiltTurns: 2 }, 400).label).toBe('behind 2 turns')
  expect(statusOf({ ...facts, runningSince: 390 }, 400).label).toBe('updating · 10s')
})

test('a fork\'s earlier messages are the user\'s own before its first new prompt; the fork point is the latest one shared', () => {
  const messages = [
    message('user', 'A'),
    message('assistant', 'a'),
    message('user', '', { toolResults: [{ tool_use_id: 'u', text: 'out', isError: false }] }),
    message('user', '<task-notification>tests passed</task-notification>'),
    message('user', 'B'),
    message('user', 'New'),
  ]
  expect(earlierPromptsOf(messages, ['New'])).toEqual(['A', 'B'])
  expect(earlierPromptsOf(messages, [])).toEqual(['A', 'B', 'New'])
  expect(forkPointOf(['ha', 'hb'], ['3:ha', '4:hb', '5:hc'])).toEqual({ turn: 4, shared: 2 })
  expect(forkPointOf(['ha', 'hx'], ['3:ha'])).toBeNull()
  expect(forkPointOf(['ha'], ['3:ha'])).toBeNull()
  expect(forkPointOf([], ['3:ha'])).toBeNull()
})

test('the model picker puts the model in use first, then Claude Code\'s families, less default, plan mode, best and 1M', async () => {
  expect(modelChoicesOf('claude-haiku-5-5', ['default', 'sonnet', 'haiku', 'best', 'sonnet[1m]', 'opusplan'])).toEqual(['claude-haiku-5-5', 'sonnet', 'haiku'])
  expect(modelChoicesOf('haiku', ['default', 'sonnet', 'haiku'])).toEqual(['haiku', 'sonnet'])
  expect(modelChoicesOf('sonnet', null)).toEqual(['sonnet', 'haiku', 'opus'])
  expect(modelChoicesOf('sonnet', ['default'])).toEqual(['sonnet', 'haiku', 'opus'])
})

test('the stats line shows total tokens, and the cached part only when every rebuild reported it', async () => {
  const base = { rebuilds: 4, inputTokens: 40_000, cachedInputTokens: 30_000, outputTokens: 4_000, wallMs: 40_000, models: ['haiku'] }
  expect(statsOf({ ...base, cachedRebuilds: 4 })).toBe('4 rebuilds · 40k tokens in, 30k cached, 4k out · avg 10.0s · haiku')
  expect(statsOf({ ...base, cachedRebuilds: 1 })).toBe('4 rebuilds · 40k tokens in, 4k out · avg 10.0s · haiku')
  // Totals saved before cached input was kept show none.
  expect(statsOf({ rebuilds: 1, inputTokens: 32_604, outputTokens: 3_220, wallMs: 16_387, models: ['claude-haiku-5-5'] })).toBe('1 rebuild · 32.6k tokens in, 3.2k out · avg 16.4s · claude-haiku-5-5')
  // A thousand thousand tokens read as millions.
  expect(statsOf({ ...base, inputTokens: 3_196_200, outputTokens: 154_100, cachedRebuilds: 1 })).toBe('4 rebuilds · 3.2M tokens in, 154.1k out · avg 10.0s · haiku')
  expect(statsOf({ ...base, inputTokens: 999_999, cachedRebuilds: 1 })).toBe('4 rebuilds · 1M tokens in, 4k out · avg 10.0s · haiku')
})

// ─── The op-set schema the model is shown, against the board's own checks ──

type FieldSchema = { type?: string; minLength?: number; maxLength?: number; enum?: string[]; items?: FieldSchema; maxItems?: number; minItems?: number; anyOf?: FieldSchema[]; $ref?: string; const?: string }
type OpSchema = { properties: Record<string, FieldSchema>; required?: string[] }

const SCHEMA = JSON.parse(OUTPUT_FORMAT.slice(OUTPUT_FORMAT.indexOf('{\n "$defs"'), OUTPUT_FORMAT.indexOf('\nOnly the content'))) as {
  $defs: Record<string, OpSchema | FieldSchema>
  properties: Record<string, FieldSchema>
}
// A field's own shape: its null branch dropped and a $ref followed.
function shapeOf(field: FieldSchema): FieldSchema {
  const inner = field.anyOf?.find(branch => branch.type !== 'null') ?? field
  return inner.$ref ? (SCHEMA.$defs[inner.$ref.split('/').at(-1) ?? ''] as FieldSchema) : inner
}
const OP_SCHEMAS = Object.values(SCHEMA.$defs).filter((def): def is OpSchema => 'properties' in def && def.properties.op?.const !== undefined)
const isTaken = (data: unknown) => {
  try {
    updateOf(data)
    return true
  } catch (error) {
    if (!(error instanceof UpdateError)) throw error
    return false
  }
}
// Each value a field's shape takes at its limits, as [case, value, whether the schema takes it].
function casesOf(shape: FieldSchema): [string, unknown, boolean][] {
  if (shape.enum) return [...shape.enum.map((value): [string, unknown, boolean] => [value, value, true]), ['value-1', 'value-1', false]]
  if (shape.type === 'array' && shape.items?.maxLength !== undefined && shape.maxItems !== undefined) {
    const item = 'x'.repeat(shape.items.maxLength)
    const fewest = shape.minItems ?? 0
    return [
      [`${shape.maxItems} items`, Array(shape.maxItems).fill(item), true],
      [`${shape.maxItems + 1} items`, Array(shape.maxItems + 1).fill(item), false],
      ...(fewest > 0 ? [[`${fewest - 1} items`, Array(fewest - 1).fill(item), false] as [string, unknown, boolean]] : []),
      ['an item past its limit', [`${item}x`], false],
    ]
  }
  if (shape.maxLength !== undefined) {
    return [
      [`${shape.maxLength} characters`, 'x'.repeat(shape.maxLength), true],
      [`${shape.maxLength + 1} characters`, 'x'.repeat(shape.maxLength + 1), false],
      ...(shape.minLength ? [['empty', '', false] as [string, unknown, boolean]] : []),
    ]
  }
  return [['text', 'text-1', true]]
}

test('the schema the model is shown names exactly the ops the board takes', () => {
  // When
  let refusal = ''
  try {
    updateOf({ ops: [{ op: 'op-1' }] })
  } catch (error) {
    refusal = (error as Error).message
  }
  // Then
  expect(refusal.replace('ops[0].op: must be one of ', '').split(', ').sort()).toEqual(OP_SCHEMAS.map(def => def.properties.op?.const).sort())
})

test('the board takes each op field the schema shows within its limits, needs the ones it requires, and refuses the rest', () => {
  const expected: [string, boolean][] = []
  const actual: [string, boolean][] = []
  for (const def of OP_SCHEMAS) {
    const op = def.properties.op?.const ?? ''
    const needed = (def.required ?? []).filter(name => name !== 'op')
    // An id makes an upsert a change, so it needs no field beside the one checked.
    const base: Record<string, unknown> = { op, ...('id' in def.properties ? { id: 'id-1' } : {}) }
    for (const name of needed) base[name] = casesOf(shapeOf(def.properties[name] ?? {}))[0]?.[1]
    for (const [name, field] of Object.entries(def.properties)) {
      if (name === 'op' || name === 'id') continue
      for (const [label, value, isTakenBySchema] of casesOf(shapeOf(field))) {
        expected.push([`${op}.${name}: ${label}`, isTakenBySchema])
        actual.push([`${op}.${name}: ${label}`, isTaken({ ops: [{ ...base, [name]: value }] })])
      }
    }
    for (const name of needed) {
      const { [name]: _left, ...without } = base
      expected.push([`${op} without ${name}`, false])
      actual.push([`${op} without ${name}`, isTaken({ ops: [without] })])
    }
    expected.push([`${op}.field-1`, false])
    actual.push([`${op}.field-1`, isTaken({ ops: [{ ...base, 'field-1': 'text-1' }] })])
  }
  expect(actual).toEqual(expected)
})

test('the board takes the op-set fields the schema shows within their limits, and refuses the rest', () => {
  const expected: [string, boolean][] = []
  const actual: [string, boolean][] = []
  for (const [name, field] of Object.entries(SCHEMA.properties)) {
    const shape = shapeOf(field)
    if (name === 'ops') {
      const op = { op: 'cta.remove', id: 'id-1' }
      expected.push([`ops: ${shape.maxItems}`, true], [`ops: ${(shape.maxItems ?? 0) + 1}`, false])
      actual.push([`ops: ${shape.maxItems}`, isTaken({ ops: Array(shape.maxItems).fill(op) })], [`ops: ${(shape.maxItems ?? 0) + 1}`, isTaken({ ops: Array((shape.maxItems ?? 0) + 1).fill(op) })])
    } else if ('properties' in shape) {
      for (const [line, lineField] of Object.entries((shape as unknown as OpSchema).properties)) {
        for (const [label, value, isTakenBySchema] of casesOf(shapeOf(lineField))) {
          expected.push([`${name}.${line}: ${label}`, isTakenBySchema])
          actual.push([`${name}.${line}: ${label}`, isTaken({ ops: [], [name]: { [line]: value } })])
        }
      }
    } else {
      for (const [label, value, isTakenBySchema] of casesOf(shape)) {
        expected.push([`${name}: ${label}`, isTakenBySchema])
        actual.push([`${name}: ${label}`, isTaken({ ops: [], [name]: value })])
      }
    }
  }
  expected.push(['field-1', false])
  actual.push(['field-1', isTaken({ ops: [], 'field-1': 'text-1' })])
  expect(actual).toEqual(expected)
})

