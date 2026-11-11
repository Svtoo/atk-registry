// The parts the band and the panes are drawn with, each one way everywhere: the chip, the count, the action and the
// word button, the fitted line, the disclosure, the stack, the heading, the view and its title, the row, the stub, the
// peek line, the divider, and the marks (an ask's badge, a warning, the plan's bar, a diagram). Pure drawing: a press
// runs the closure the caller hands in.
import type { ElementTable, RenderElement, RenderSurface } from 'claude-code'

import type { DebriefFreeformPart, DebriefTodoStatus } from '../types'
import { COLORS, TODO_COLORS, textColorOf } from './colors'
import { BADGE_PX, type BarShare, badgeSvg, barSvg, barWidthOf, warningSvg } from './marks'

/** What each act looks like, on every button that does it. */
export const GLYPHS = {
  reply: '❝',
  done: '✓',
  dismiss: '🗑',
  undo: '↶',
  open: '▾',
  closed: '▸',
  rebuild: '↻',
  settings: '⚙',
  previous: '←',
  next: '→',
} as const

// The tint of a view on the desktop band: a see-through grey, which shades a light theme as it does a dark one. The
// terminal draws a view by its frame alone, since its colours take no see-through.
const VIEW_TINT = '#8080801f'

// The box of a line cut to fit its row: it takes the room the row leaves, and with minWidth 0 the desktop shrinks it
// below its text, so a long line does not push the row's buttons out of view.
const FILLS_ROW = { flexGrow: 1, flexShrink: 1, minWidth: 0 } as const

// A desktop draws its native button, which reads as a control; the terminal keeps the plain look, which shows the
// hotkey and spares a bracket pair per control on the header line.
function chromeOf(surface: RenderSurface): { plain?: true } {
  return surface === 'terminal' ? { plain: true } : {}
}

type Node = RenderElement | string | null | false | undefined | Node[]

/** The parts, drawn with the surface's own elements. */
export function kitOf(ui: ElementTable, surface: RenderSurface) {
  const { Box, Text, Button } = ui
  const chrome = chromeOf(surface)
  // The terminal lists Svg but draws it as an empty Box.
  const Svg = surface === 'terminal' || !('Svg' in ui) ? null : ui.Svg
  // A desktop button stands taller than a line of text, so rows that end in buttons sit a gap apart there.
  const rowGap = surface === 'terminal' ? undefined : 1
  // A hint: a hidden label below a header control, shown while the pointer is over the keyed box that holds it, out of
  // the flow, so it moves nothing as it shows; it lines up with the control's right edge. Only the header's controls
  // have one: below the header a hint would cover the buttons under it. The terminal has no pointer to show it; its
  // buttons show their hotkeys.
  const hinted = (key: string, hint: string | null, control: RenderElement) =>
    !hint || surface === 'terminal' ? (
      control
    ) : (
      <Box key={`hint-${key}`} flexShrink={0}>
        {control}
        <Box position="absolute" top={2} right={0} width={hint.length + 2} justifyContent="flex-end" display="none" hover={{ display: 'flex' }}>
          <Text inverse>{` ${hint} `}</Text>
        </Box>
      </Box>
    )
  /** A heading row: what it is on the left, its controls on the right, as a view's title row and the pager have. */
  const heading = (key: string, title: Node, controls: Node[]) => (
    <Box key={key} flexDirection="row" gap={1}>
      {title}
      <Box flexGrow={1} />
      {controls}
    </Box>
  )
  function barOf(shares: BarShare[], alt: string) {
    if (shares.length === 0) return null
    if (Svg) return <Svg source={barSvg(shares)} alt={alt} width={barWidthOf(shares)} height={BADGE_PX} />
    return (
      <Box flexDirection="row">
        {shares.map(share => (
          <Text color={textColorOf(TODO_COLORS[share.status])}>{(share.status === 'open' ? '□' : '■').repeat(share.cells)}</Text>
        ))}
      </Box>
    )
  }
  return {
    rowGap,
    /**
     * A chip on the header opens a view or a pane: open, it is the filled primary button; closed, it is dim. Its label
     * says what it is, so it has no hint, unless the label is too short to say it, as the status chip's dot and time.
     */
    chip: ({ key, label, isOpen, onPress, hint = null }: { key: string; label: string; isOpen: boolean; onPress: () => void; hint?: string | null }) =>
      hinted(key, hint, <Button key={key} {...chrome} {...(isOpen ? { variant: 'primary' as const } : { dimColor: true })} label={label} onPress={onPress} />),
    /** A count on the header with no view of its own: text, never a button, kept whole on a narrow band. */
    count: (key: string, label: string) => (
      <Box key={key} flexShrink={0}>
        <Text dimColor>{label}</Text>
      </Box>
    ),
    /**
     * One act, one glyph: dim unless it is the act a row is for, with a hotkey where the terminal offers one, and on the
     * header a hint that says what it does.
     */
    action: (
      key: string,
      glyph: string,
      onPress: () => void,
      { isDim = true, hotkey, hint = null }: { isDim?: boolean; hotkey?: string; hint?: string | null } = {},
    ) => hinted(key, hint, <Button key={key} {...chrome} dimColor={isDim} {...(hotkey ? { hotkey } : {})} label={glyph} onPress={onPress} />),
    /** A control labelled in words, which says what it does itself, so it has no hint. */
    button: (key: string, label: string, onPress: () => void, { isDim = true }: { isDim?: boolean } = {}) => (
      <Button key={key} {...chrome} dimColor={isDim} label={label} onPress={onPress} />
    ),
    /** A line that gives way on a narrow row: as wide as its text, cut to fit when the row runs short, so what follows it keeps its width. */
    fit: (line: Node, key: string) => (
      <Box key={key} flexShrink={1} minWidth={0}>
        {line}
      </Box>
    ),
    /** Folds a part of a view in place: ▸ closed, ▾ open. */
    disclosure: (key: string, label: string, isOpen: boolean, onPress: () => void) => (
      <Button key={key} {...chrome} dimColor label={`${isOpen ? GLYPHS.open : GLYPHS.closed} ${label}`} onPress={onPress} />
    ),
    /** A column of rows that may end in buttons, a gap apart where the buttons need it. */
    stack: (key: string, rows: Node[]) => (
      <Box key={key} flexDirection="column" rowGap={rowGap}>
        {rows}
      </Box>
    ),
    heading,
    /** A view under the header: a tinted, framed box whose title row holds its controls, then its rows. */
    view: (key: string, title: Node, controls: Node[], rows: Node[]) => (
      <Box
        key={key}
        flexDirection="column"
        rowGap={rowGap}
        paddingX={1}
        paddingY={1}
        {...(surface === 'terminal' ? {} : { backgroundColor: VIEW_TINT })}
        borderStyle="single"
        borderDimColor
      >
        {heading(`${key}-title`, title, controls)}
        {rows}
      </Box>
    ),
    /** A view's title: its mark, its name in bold, then its counts dim. */
    title: (name: string, counts: string, mark?: Node) => (
      <Box flexDirection="row" gap={1} flexShrink={1}>
        {mark}
        <Text bold>{name}</Text>
        {counts && <Text dimColor>{counts}</Text>}
      </Box>
    ),
    /** A row: its mark, its text, its age, then its actions; the same columns in every list. */
    row: (key: string, content: Node, { mark, age, actions = [] }: { mark?: Node; age?: string; actions?: Node[] } = {}) => (
      <Box key={key} flexDirection="row" gap={1} alignItems="flex-start">
        {mark}
        <Box flexDirection="column" {...FILLS_ROW}>
          {content}
        </Box>
        {age && <Text dimColor>{age}</Text>}
        {actions.length > 0 && (
          <Box flexDirection="row" gap={1} flexShrink={0}>
            {actions}
          </Box>
        )}
      </Box>
    ),
    /** An item set aside until the next rebuild: struck through (or dim, for one only acknowledged), with ↶. */
    stub: (key: string, text: string, undoKey: string, onUndo: () => void, { isStruck = true, mark }: { isStruck?: boolean; mark?: Node } = {}) => (
      <Box key={key} flexDirection="row" gap={1}>
        {mark}
        <Box {...FILLS_ROW}>
          <Text strikethrough={isStruck || undefined} dimColor wrap="truncate">
            {text}
          </Text>
        </Box>
        <Button key={undoKey} {...chrome} label={GLYPHS.undo} onPress={onUndo} />
      </Box>
    ),
    /** A dim rule across the body: the desktop fits fewer dashes than the columns, so it draws twice as many, cut at the edge. */
    divider: (key: string, columns: number) => (
      <Box key={key} flexDirection="row">
        {/* The line runs past the row and the site clips it; a box that shrank to the row would end it in "…". */}
        <Box flexGrow={1} flexShrink={1}>
          <Text dimColor wrap="truncate">
            {'─'.repeat(columns * (surface === 'terminal' ? 1 : 2))}
          </Text>
        </Box>
      </Box>
    ),
    /** An ask's number in a circle of its colour; on the terminal, the number on that colour. */
    badge: (n: number, color: string) =>
      Svg ? (
        <Svg source={badgeSvg(n, color)} alt={`ask ${n}`} width={BADGE_PX} height={BADGE_PX} />
      ) : (
        <Text bold color={COLORS.white} backgroundColor={color}>{` ${n} `}</Text>
      ),
    /** A warning triangle in its colour, named for what it warns of. */
    warning: (color: string, alt: string) =>
      Svg ? <Svg source={warningSvg(color)} alt={alt} width={BADGE_PX} height={BADGE_PX} /> : <Text bold color={textColorOf(color)}>⚠</Text>,
    /** The plan's bar, a cell per share; on the terminal, filled and hollow squares. Nothing for an empty plan. */
    bar: (shares: BarShare[], alt: string) => barOf(shares, alt),
    /** One step's cell, as the bar draws it. */
    cell: (status: DebriefTodoStatus) => barOf([{ status, count: 1, cells: 1 }], status),
    /** A card's diagram; the terminal names it. */
    diagram: (part: Extract<DebriefFreeformPart, { kind: 'svg' }>) =>
      Svg ? (
        <Svg source={part.source} alt={part.alt} {...(part.width ? { width: part.width } : {})} {...(part.height ? { height: part.height } : {})} />
      ) : (
        <Text dimColor>{`[diagram: ${part.alt}]`}</Text>
      ),
    /** A line that says a list has nothing to show, in the asks' own words: "✓ Nothing pending". */
    empty: (key: string, text: string) => (
      <Box key={key}>
        <Text color={textColorOf(COLORS.green)}>{`✓ ${text}`}</Text>
      </Box>
    ),
    /** A peek line: one dim line cut to fit, with no controls. */
    peek: (key: string, mark: Node, text: string) => (
      <Box key={key} flexDirection="row" gap={1}>
        {mark}
        <Box {...FILLS_ROW}>
          <Text dimColor wrap="truncate">
            {text}
          </Text>
        </Box>
      </Box>
    ),
  }
}
