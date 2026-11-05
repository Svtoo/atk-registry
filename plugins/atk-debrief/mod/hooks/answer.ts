// The rebuild model's answer: an <update> block holding the change set as JSON, then one <freeform ref="…"> block per
// card body. The blocks are found by plain text search; whatever the model writes around them is ignored. Pure.

import { FREEFORM_MAX, type Update, UpdateError, updateOf } from './board'

/** The answer holds no usable change set, or a diagram that cannot be drawn: the board stays as it was. */
export class AnswerError extends Error {}

const UPDATE_OPEN = '<update>'
const UPDATE_CLOSE = '</update>'
const CARD_OPEN = '<freeform ref="'
const CARD_CLOSE = '</freeform>'

// A diagram is an <svg> block that starts a line, as band-model.ts cuts a card into its parts.
export const SVG_BLOCK = /^<svg\b[\s\S]*?<\/svg>/gim
const SVG_OPEN = /^<svg\b/gim
// A diagram draws as a picture, so no code may run in it and no HTML may hide inside it.
const SVG_CODE = /<script|<foreignObject|\son[a-z]+\s*=|javascript:/i

/** Every closed `<freeform ref="ID">…</freeform>` block's body by its ref; an unclosed last block has none. */
function cardBodiesOf(raw: string): Record<string, string> {
  const bodies: Record<string, string> = {}
  let at = 0
  for (;;) {
    const open = raw.indexOf(CARD_OPEN, at)
    if (open === -1) break
    const refStart = open + CARD_OPEN.length
    const refEnd = raw.indexOf('"', refStart)
    const gt = refEnd === -1 ? -1 : raw.indexOf('>', refEnd)
    if (gt === -1) break
    const close = raw.indexOf(CARD_CLOSE, gt)
    if (close === -1) break
    bodies[raw.slice(refStart, refEnd)] = raw.slice(gt + 1, close).replace(/^\n+|\n+$/g, '')
    at = close + CARD_CLOSE.length
  }
  return bodies
}

const NAME = /^[A-Za-z_:][\w:.-]*$/
const ENTITY = /&(?:#\d+|#x[0-9a-fA-F]+|[A-Za-z][\w.-]*);/g
const XML_ENTITIES = new Set(['&amp;', '&lt;', '&gt;', '&quot;', '&apos;'])

function badEntityIn(text: string): string | null {
  if (/&(?!(?:#\d+|#x[0-9a-fA-F]+|[A-Za-z][\w.-]*);)/.test(text)) return 'a bare &'
  for (const match of text.matchAll(ENTITY)) if (!match[0].startsWith('&#') && !XML_ENTITIES.has(match[0])) return `undefined entity ${match[0]}`
  return null
}

/** Why the text is not well-formed XML, or null: tags nest and close, attributes are quoted, entities are XML's own. */
export function xmlProblem(xml: string): string | null {
  const stack: string[] = []
  let at = 0
  let hasRoot = false
  while (at < xml.length) {
    const lt = xml.indexOf('<', at)
    const text = xml.slice(at, lt === -1 ? xml.length : lt)
    if (stack.length === 0 && text.trim()) return 'text outside the root element'
    const entity = badEntityIn(text)
    if (entity) return entity
    if (lt === -1) break
    if (xml.startsWith('<!--', lt)) {
      const end = xml.indexOf('-->', lt + 4)
      if (end === -1) return 'an unclosed comment'
      at = end + 3
      continue
    }
    if (xml.startsWith('<![CDATA[', lt)) {
      const end = xml.indexOf(']]>', lt)
      if (end === -1) return 'an unclosed CDATA section'
      at = end + 3
      continue
    }
    if (xml.startsWith('<?', lt) || xml.startsWith('<!', lt)) {
      const end = xml.indexOf('>', lt)
      if (end === -1) return 'an unclosed declaration'
      at = end + 1
      continue
    }
    // The tag runs to the first > outside a quoted value.
    let end = lt + 1
    let quote = ''
    for (; end < xml.length; end++) {
      const ch = xml[end]
      if (quote) {
        if (ch === quote) quote = ''
      } else if (ch === '"' || ch === "'") quote = ch
      else if (ch === '>') break
      else if (ch === '<') return 'a < inside a tag'
    }
    if (end >= xml.length) return 'an unclosed tag'
    const tag = xml.slice(lt + 1, end)
    at = end + 1
    if (tag.startsWith('/')) {
      const name = tag.slice(1).trim()
      const open = stack.pop()
      if (open !== name) return open ? `</${name}> closes <${open}>` : `</${name}> closes nothing`
      continue
    }
    const isEmpty = tag.endsWith('/')
    const inner = isEmpty ? tag.slice(0, -1) : tag
    const name = inner.match(/^[^\s]+/)?.[0] ?? ''
    if (!NAME.test(name)) return `a bad tag name <${name}>`
    if (stack.length === 0 && hasRoot) return 'more than one root element'
    const attrs = inner.slice(name.length)
    const seen = new Set<string>()
    const ATTR = /\s+([^\s=]+)\s*=\s*("[^"]*"|'[^']*')/y
    let pos = 0
    for (;;) {
      ATTR.lastIndex = pos
      const match = ATTR.exec(attrs)
      if (!match) break
      const [, attr = '', value = ''] = match
      if (!NAME.test(attr)) return `a bad attribute name ${attr}`
      if (seen.has(attr)) return `the attribute ${attr} twice`
      seen.add(attr)
      if (value.includes('<')) return `a < in the value of ${attr}`
      const entity = badEntityIn(value)
      if (entity) return entity
      pos = ATTR.lastIndex
    }
    if (attrs.slice(pos).trim()) return `a bad attribute in <${name}>`
    if (stack.length === 0) hasRoot = true
    if (!isEmpty) stack.push(name)
  }
  if (stack.length > 0) return `<${stack[stack.length - 1]}> is not closed`
  return hasRoot ? null : 'no element'
}

/** Why a card's diagrams cannot be drawn, or null when every one can. */
function svgProblem(body: string): string | null {
  const svgs = body.match(SVG_BLOCK) ?? []
  if (svgs.length !== (body.match(SVG_OPEN) ?? []).length) return 'an <svg> block is not closed'
  for (const svg of svgs) {
    if (SVG_CODE.test(svg)) return 'an <svg> block holds a script, an event handler or embedded HTML'
    const problem = xmlProblem(svg)
    if (problem) return `an <svg> block is not well-formed XML (${problem})`
  }
  return null
}

export type Answer = { update: Update; bodies: Record<string, string>; notes: string[] }

/**
 * The change set's JSON and where its block ends. The model may reason before its blocks, and its reasoning may name
 * the tags, so the block read is the last closed one whose content is JSON; with none, the last closed one's error.
 */
function updateBlockOf(raw: string): { data: unknown; end: number } {
  const blocks: { body: string; end: number }[] = []
  for (let open = raw.indexOf(UPDATE_OPEN); open !== -1; open = raw.indexOf(UPDATE_OPEN, open + 1)) {
    const close = raw.indexOf(UPDATE_CLOSE, open + UPDATE_OPEN.length)
    if (close !== -1) blocks.push({ body: raw.slice(open + UPDATE_OPEN.length, close).trim(), end: close + UPDATE_CLOSE.length })
  }
  if (blocks.length === 0) throw new AnswerError('no complete <update>…</update> block in the reply')
  let problem = ''
  for (const block of blocks.reverse()) {
    try {
      return { data: JSON.parse(block.body), end: block.end }
    } catch (error) {
      problem ||= (error as Error).message
    }
  }
  throw new AnswerError(`<update> block is not valid JSON: ${problem}`)
}

/**
 * The answer's change set, checked, with each card's body by its ref. A card op whose body is missing, too long, or in
 * the notices' markup is dropped with a note; the rest still applies. No closed <update> block, bad JSON, a broken
 * schema or an undrawable diagram throws an AnswerError, and the board stays as it was.
 */
export function parseAnswer(raw: string): Answer {
  const { data, end } = updateBlockOf(raw)
  let update: Update
  try {
    update = updateOf(data)
  } catch (error) {
    if (error instanceof UpdateError) throw new AnswerError(`op-set failed schema validation: ${error.message}`)
    throw error
  }

  const bodies = cardBodiesOf(raw.slice(end))
  const notes: string[] = []
  const kept = []
  for (const op of update.ops) {
    if (op.op !== 'freeform.upsert') {
      kept.push(op)
      continue
    }
    const body = bodies[op.bodyRef]
    if (body === undefined) {
      notes.push(`dropped freeform.upsert ref=${op.bodyRef}: no matching <freeform> block`)
      continue
    }
    if (body.length > FREEFORM_MAX) {
      notes.push(`dropped freeform.upsert ref=${op.bodyRef}: body ${body.length} chars over the ${FREEFORM_MAX} limit`)
      continue
    }
    const problem = svgProblem(body)
    if (problem) throw new AnswerError(`freeform ref=${op.bodyRef}: ${problem}; fix the diagram and send the card again`)
    kept.push(op)
  }
  return { update: { ...update, ops: kept }, bodies, notes }
}
