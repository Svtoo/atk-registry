// The band above the prompt, drawn from what it shows (DebriefBand), how the person has laid it out (BandLook) and
// what each press does (BandActs). Pure drawing: only a hook's own file may touch `$` or an atom, so register.tsx reads
// the atoms and builds the presses, and this file draws with the kit.
import type { ElementTable, RenderElement, RenderSurface } from 'claude-code'

import type { DebriefBand, DebriefBandView, DebriefFreshness, DebriefHeadsup, DebriefNotice, DebriefPhase, DebriefTodo } from '../types'
import { agoSince, barOf, isLiveCard, linkIconOf, markdownLinkOf, noticeReplyOf, plainOf, replyOf, stepOf, todoAgeOf, whereOf } from './band-model'
import { ageColor, COLORS, textColorOf } from './colors'
import { GLYPHS, kitOf } from './kit'
import type { CallOf } from './rebuild'
import { SETTINGS_COMMAND } from './status'

// The turn's mark on the header: a turn opens at each message the user sends.
const TURN_GLYPH = '💬'

// The dot that colours the status chip, in its label so it reads as the chip's own.
const STATUS_DOTS: Record<DebriefFreshness, string> = { current: '🟢', updating: '🔵', behind: '🟡', failed: '🔴' }

const PHASE_LOOKS: Record<DebriefPhase, { label: string; color: string }> = {
  planning: { label: 'Planning', color: COLORS.indigo },
  building: { label: 'Building', color: COLORS.green },
  blocked: { label: 'Blocked', color: COLORS.red },
  review: { label: 'Awaiting review', color: COLORS.amber },
  shipped: { label: 'Shipped', color: COLORS.green },
}

const PROBLEM_COLORS: Record<DebriefNotice['severity'], string> = { blocked: COLORS.red, degraded: COLORS.amber, bug: COLORS.indigo, info: COLORS.grey }

const HEADSUP_COLORS: Record<DebriefHeadsup['sev'], string> = { risk: COLORS.red, flag: COLORS.amber }

const SETTINGS_LABEL = '⚙ settings'

/** How the person has laid the band out, from the session's atoms. */
export type BandLook = {
  openView: DebriefBandView | null
  isFolded: boolean
  isAckedOpen: boolean
  isDoneOpen: boolean
  isResolvedOpen: boolean
  isFreeformOpen: boolean
  openNoticeIds: string[]
}

/** What each press does; register.tsx builds them over `$`, each saving or toggling and saying when a save fails. */
export type BandActs = {
  toggleView: (view: DebriefBandView) => void
  toggleFold: () => void
  rebuild: () => void
  toggleFreeform: () => void
  reply: (text: string) => void
  setAsk: (id: string, call: CallOf<'cta'> | null) => void
  setStep: (id: string, call: CallOf<'todo'> | null) => void
  acknowledge: (id: string, isAcknowledged: boolean) => void
  toggleAcked: () => void
  toggleDone: () => void
  toggleDetail: (id: string) => void
  dismissProblem: (id: string, isDismissed: boolean) => void
  toggleResolved: () => void
  openSettings: () => void
}

/** Which views have anything to show: a chip shows only for those, and a view opens only while it does. */
export function viewsOf(b: DebriefBand): Record<DebriefBandView, boolean> {
  return {
    links: b.links.length > 0,
    headsups: b.headsups.length + b.ackedHeadsups.length > 0,
    todos: b.todos.length > 0,
    status: b.hasDashboard || b.status.freshness !== 'current',
  }
}

export function drawBand(ui: ElementTable, surface: RenderSurface, b: DebriefBand, look: BandLook, acts: BandActs): RenderElement {
  const { Box, Text, Markdown } = ui
  const k = kitOf(ui, surface)
  // ❝ quotes the item into the prompt box, to answer it; the one act on a row drawn bright.
  const replyTo = (key: string, text: string) => k.action(key, GLYPHS.reply, 'Reply: quote it in the prompt box', () => acts.reply(text), { isDim: false })

  const plan = b.todos.filter(todo => !todo.isDropped)
  const bar = barOf(plan)
  const doneCount = plan.filter(todo => todo.status === 'done').length
  const barAlt = `${doneCount} of ${plan.length} done`
  // Steps a rebuild has marked done fold behind the done toggle; a step checked in the band stays in place, with ↶,
  // until a rebuild takes it in.
  const isBoardDone = (todo: DebriefTodo) => todo.status === 'done' && !todo.isChecked
  const boardDone = b.todos.filter(isBoardDone)
  const step = stepOf(plan)
  const liveCards = b.freeform.filter(isLiveCard).length
  const [worst] = b.headsups
  const openAsks = b.asks.filter(ask => !ask.isDismissed).length

  const headsupRow = (headsup: DebriefHeadsup) => {
    const where = whereOf(headsup)
    return k.row(
      `headsup-${headsup.id}`,
      [<Markdown text={headsup.what} />, <Markdown dimColor text={`why: ${headsup.why}`} />, where && <Markdown dimColor text={where} />],
      {
        mark: k.warning(HEADSUP_COLORS[headsup.sev], headsup.sev),
        age: agoSince(headsup.raisedTurn, b.turn),
        actions: [
          replyTo(`reply-headsup-${headsup.id}`, replyOf(headsup)),
          k.action(`ack-${headsup.id}`, GLYPHS.done, 'Acknowledge', () => acts.acknowledge(headsup.id, true)),
        ],
      },
    )
  }
  const headsupsView = () =>
    k.view(
      'view-headsups',
      k.title('⚠️ Heads-up', `· ${b.headsups.length} open`),
      [b.ackedHeadsups.length > 0 && k.disclosure('acked-toggle', `${b.ackedHeadsups.length} acknowledged`, look.isAckedOpen, acts.toggleAcked)],
      [
        b.headsups.length === 0 && !look.isAckedOpen && k.empty('headsups-empty', 'No open heads-up'),
        ...b.headsups.map(headsupRow),
        ...(look.isAckedOpen
          ? b.ackedHeadsups.map(headsup =>
              k.stub(`acked-${headsup.id}`, plainOf(headsup.what), `unack-${headsup.id}`, () => acts.acknowledge(headsup.id, false), { isStruck: false }),
            )
          : []),
      ],
    )

  const todoRow = (todo: DebriefTodo) => {
    if (todo.isDropped) return k.stub(`todo-${todo.id}`, plainOf(todo.text), `undrop-${todo.id}`, () => acts.setStep(todo.id, null))
    // A step checked here keeps its done cell, so it reads apart from a dropped one until a rebuild takes it in.
    if (todo.isChecked) return k.stub(`todo-${todo.id}`, plainOf(todo.text), `uncheck-${todo.id}`, () => acts.setStep(todo.id, null), { mark: k.cell('done') })
    const isDone = isBoardDone(todo)
    const isCheckable = todo.status === 'open' || todo.status === 'active'
    return k.row(`${isDone ? 'done' : 'todo'}-${todo.id}`, <Markdown dimColor={isDone} text={todo.text} />, {
      mark: k.cell(todo.status),
      age: todoAgeOf(todo, b.turn),
      actions: isDone
        ? []
        : [
            isCheckable && k.action(`check-${todo.id}`, GLYPHS.done, 'Mark the step done', () => acts.setStep(todo.id, 'done')),
            k.action(`drop-${todo.id}`, GLYPHS.dismiss, 'Drop the step', () => acts.setStep(todo.id, 'dropped')),
          ],
    })
  }
  const todosView = () => {
    const shown = [...(look.isDoneOpen ? boardDone : []), ...b.todos.filter(todo => !boardDone.includes(todo))]
    return k.view(
      'view-todos',
      k.title('📋 To-do', `· ${plan.length - doneCount} open · ${doneCount} done`, k.bar(bar, barAlt)),
      [boardDone.length > 0 && k.disclosure('done-toggle', `${boardDone.length} done`, look.isDoneOpen, acts.toggleDone)],
      shown.length === 0 ? [k.empty('todos-empty', 'Every step done')] : shown.map(todoRow),
    )
  }

  const problemStack = (problem: DebriefNotice) => {
    const isDetailOpen = look.openNoticeIds.includes(problem.id)
    return k.stack(`notice-${problem.id}`, [
      k.row(`notice-head-${problem.id}`, <Text bold>{problem.title}</Text>, {
        mark: k.warning(PROBLEM_COLORS[problem.severity], problem.severity),
        age: problem.count > 1 ? `× ${problem.count} · ${problem.ago}` : problem.ago,
        actions: [
          k.action(`notice-details-${problem.id}`, isDetailOpen ? GLYPHS.open : GLYPHS.closed, isDetailOpen ? 'Hide the details' : 'Show the details', () =>
            acts.toggleDetail(problem.id),
          ),
          replyTo(`reply-notice-${problem.id}`, noticeReplyOf(problem)),
          problem.dismiss === 'ack' && k.action(`dismiss-notice-${problem.id}`, GLYPHS.dismiss, 'Dismiss the problem', () => acts.dismissProblem(problem.id, true)),
        ],
      }),
      <Text dimColor>{problem.what}</Text>,
      ...problem.steps.map((step, index) => (
        <Box key={`step-${problem.id}-${index + 1}`} flexDirection="row" gap={1}>
          <Text dimColor>{`${index + 1}.`}</Text>
          <Text>{step.text}</Text>
          {step.command === `/${SETTINGS_COMMAND}`
            ? k.button(`settings-${problem.id}`, SETTINGS_LABEL, acts.openSettings, { isDim: false })
            : step.command && <Markdown text={`\`${step.command}\``} />}
          {step.href && <Markdown text={markdownLinkOf(step.hrefLabel || step.href, step.href)} />}
        </Box>
      )),
      isDetailOpen && (
        <Box key={`notice-detail-${problem.id}`} flexDirection="column">
          {problem.diagnostics.length > 0 && <Text dimColor>{problem.diagnostics.map(item => `${item.label}: ${item.value}`).join(' · ')}</Text>}
          {problem.detail && <Markdown dimColor text={`\`\`\`\n${problem.detail}\n\`\`\``} />}
        </Box>
      ),
    ])
  }
  const statusView = () =>
    k.view(
      'view-status',
      k.title(`${STATUS_DOTS[b.status.freshness]} Status`, `· ${b.status.label}`),
      [
        b.status.resolvedNotices.length > 0 && k.disclosure('resolved-toggle', `${b.status.resolvedNotices.length} resolved`, look.isResolvedOpen, acts.toggleResolved),
      ],
      [
        b.status.stats && (
          <Box key="status-stats">
            <Text dimColor>{b.status.stats}</Text>
          </Box>
        ),
        b.status.notices.length === 0 && k.empty('status-empty', 'No problems'),
        ...b.status.notices.map(problemStack),
        ...b.status.dismissedNotices.map(problem => k.stub(`dismissed-${problem.id}`, problem.title, `undismiss-${problem.id}`, () => acts.dismissProblem(problem.id, false))),
        ...(look.isResolvedOpen
          ? b.status.resolvedNotices.map(problem => k.row(`resolved-${problem.id}`, <Text dimColor>{problem.title}</Text>, { age: `resolved ${problem.ago}` }))
          : []),
      ],
    )

  const linksView = () =>
    k.view(
      'view-links',
      k.title('🔗 Links', `· ${b.links.length}`),
      [],
      b.links.map(link =>
        k.row(
          `link-${link.id}`,
          <Box key={`kind-link-${link.id}`} flexDirection="row" gap={1}>
            <Text dimColor>{link.kind}</Text>
            <Markdown text={markdownLinkOf(link.label, link.url)} />
          </Box>,
          { mark: <Text>{linkIconOf(link.kind)}</Text> },
        ),
      ),
    )
  const views: Record<DebriefBandView, () => RenderElement> = { links: linksView, headsups: headsupsView, todos: todosView, status: statusView }
  const hasView = viewsOf(b)
  const shownView = look.openView && hasView[look.openView] ? look.openView : null
  // A folded band shows no view, so no chip on it reads open.
  const chipOf = (view: DebriefBandView, label: string, hint: string | null = null) =>
    hasView[view] && k.chip({ key: view, label, hint, isOpen: !look.isFolded && shownView === view, onPress: () => acts.toggleView(view) })
  // The status chip: its dot and time, with the state in words in its hint; the terminal, which has no pointer, keeps
  // the words in the chip.
  const dot = STATUS_DOTS[b.status.freshness]
  const statusChip =
    surface === 'terminal'
      ? chipOf('status', `${dot} ${b.status.label}`)
      : chipOf('status', b.status.time === null ? dot : `${dot} ${b.status.time}`, b.status.label)

  const phase = b.phase && PHASE_LOOKS[b.phase]
  // On a narrow band the phase is cut first, down to the turn; then the chips and controls wrap onto more lines,
  // right-aligned, so none runs off the edge.
  const header = (
    <Box flexDirection="row" gap={1}>
      {phase && (
        <Box key="header-phase" flexDirection="row" gap={1} flexShrink={100}>
          {k.fit(
            <Text color={textColorOf(phase.color)} wrap="truncate">
              {phase.label}
            </Text>,
            { key: 'phase-label', text: `Phase: ${phase.label}`, at: 'below' },
          )}
          {k.count('turn', `· ${TURN_GLYPH} ${b.turn}`)}
        </Box>
      )}
      <Box key="header-controls" flexDirection="row" flexWrap="wrap" justifyContent="flex-end" gap={1} rowGap={k.rowGap} flexGrow={1} flexShrink={1}>
        {openAsks > 0 && k.count('asks-count', `📥 ${openAsks}`)}
        {chipOf('links', `🔗 ${b.links.length}`)}
        {/* The chip stays while the chat has any card, so dismissed ones stay reachable. */}
        {(b.freeform.length > 0 || look.isFreeformOpen) &&
          k.chip({
            key: 'freeform',
            label: liveCards > 0 || b.freeform.length === 0 ? `🧩 ${liveCards}` : `🧩 ${b.freeform.length} dismissed`,
            isOpen: look.isFreeformOpen,
            onPress: acts.toggleFreeform,
          })}
        {chipOf('headsups', `⚠️ ${b.headsups.length}`)}
        {chipOf('todos', `📋 ${doneCount}/${plan.length}`)}
        {statusChip}
        <Box flexDirection="row" gap={1} marginLeft={1}>
          {k.action('settings', GLYPHS.settings, 'Open the settings', acts.openSettings, { hintAt: 'below' })}
          {k.action('rebuild', GLYPHS.rebuild, 'Rebuild the dashboard', acts.rebuild, { hotkey: 'r', hintAt: 'below' })}
          {k.action('band-fold', look.isFolded ? GLYPHS.closed : GLYPHS.open, look.isFolded ? 'Unfold the band' : 'Fold the band', acts.toggleFold, { hintAt: 'below' })}
        </Box>
      </Box>
    </Box>
  )
  if (look.isFolded) return <Box flexDirection="column">{header}</Box>

  return (
    <Box flexDirection="column" rowGap={k.rowGap}>
      {header}
      {shownView && views[shownView]()}
      {b.lastTurn && (
        <Box flexDirection="column">
          {b.lastTurn.bullets.map(bullet => (
            <Box flexDirection="row">
              <Text color={textColorOf(COLORS.green)}>{'• '}</Text>
              <Box flexGrow={1} flexShrink={1}>
                <Markdown text={bullet} />
              </Box>
            </Box>
          ))}
        </Box>
      )}
      {!b.hasDashboard && (
        <Box key="first-build">
          <Text dimColor>{b.status.freshness === 'updating' ? "Building this chat's first dashboard…" : 'No dashboard yet. It builds when a turn ends.'}</Text>
        </Box>
      )}
      {b.hasDashboard &&
        k.stack('asks', [
          b.asks.length === 0 && <Text color={textColorOf(COLORS.green)}>✓ Nothing pending</Text>,
          ...b.asks.map((ask, index) => {
            if (ask.isDismissed) return k.stub(`ask-${ask.id}`, plainOf(ask.text), `undo-${ask.id}`, () => acts.setAsk(ask.id, null))
            return k.row(`ask-${ask.id}`, <Markdown text={ask.text} />, {
              mark: k.badge(index + 1, ageColor(ask.age)),
              actions: [replyTo(`reply-${ask.id}`, plainOf(ask.text)), k.action(`dismiss-${ask.id}`, GLYPHS.dismiss, 'Dismiss the ask', () => acts.setAsk(ask.id, 'dismissed'))],
            })
          }),
        ])}
      {/* The peek lines: the step in progress and the worst heads-up, while their view is closed. */}
      {((step && shownView !== 'todos') || (worst && shownView !== 'headsups')) && (
        <Box key="peeks" flexDirection="column">
          {step && shownView !== 'todos' && k.peek('todos-peek', k.bar(bar, barAlt), `${doneCount}/${plan.length} · ${plainOf(step.text)}`)}
          {worst && shownView !== 'headsups' && k.peek('headsups-peek', k.warning(HEADSUP_COLORS[worst.sev], worst.sev), plainOf(worst.what))}
        </Box>
      )}
    </Box>
  )
}
