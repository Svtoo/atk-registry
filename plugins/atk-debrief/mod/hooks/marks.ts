// The small pictures the desktop draws as Svg: an ask's number, a warning triangle, the plan's bar. Pure strings; the
// kit draws them, or their text stand-ins where Svg is not drawn.
import type { DebriefTodoStatus } from '../types'
import { COLORS, TODO_COLORS } from './colors'

export const BADGE_PX = 18

/** A numbered circle for an ask. */
export function badgeSvg(n: number, color: string): string {
  const r = BADGE_PX / 2
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${BADGE_PX}" height="${BADGE_PX}" viewBox="0 0 ${BADGE_PX} ${BADGE_PX}">
<circle cx="${r}" cy="${r}" r="${r}" fill="${color}"/>
<text x="${r}" y="${r}" text-anchor="middle" dominant-baseline="central" fill="${COLORS.white}" font-family="-apple-system, system-ui, sans-serif" font-size="11" font-weight="700">${n}</text>
</svg>`
}

/** A warning triangle, as the band marks a heads-up and a problem. */
export function warningSvg(color: string): string {
  const s = BADGE_PX
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${s}" height="${s}" viewBox="0 0 ${s} ${s}">
<path d="M${s / 2} 1.5 L${s - 1} ${s - 2} L1 ${s - 2} Z" fill="${color}"/>
<text x="${s / 2}" y="${s - 3.5}" text-anchor="middle" fill="${COLORS.white}" font-family="-apple-system, system-ui, sans-serif" font-size="10" font-weight="700">!</text>
</svg>`
}

/** The bar's cells of one status. */
export type BarShare = { status: DebriefTodoStatus; count: number; cells: number }

const CELL_PX = 10
const CELL_GAP_PX = 2

export const cellsOf = (shares: BarShare[]) => shares.flatMap(share => Array<DebriefTodoStatus>(share.cells).fill(share.status))

export const barWidthOf = (shares: BarShare[]) => cellsOf(shares).length * (CELL_PX + CELL_GAP_PX) - CELL_GAP_PX

/** A row of square cells; an open step is an outline. */
export function barSvg(shares: BarShare[]): string {
  const width = barWidthOf(shares)
  const y = (BADGE_PX - CELL_PX) / 2
  const rects = cellsOf(shares).map((status, index) => {
    const x = index * (CELL_PX + CELL_GAP_PX)
    const paint = status === 'open' ? `fill="none" stroke="${TODO_COLORS.open}" stroke-width="1.5"` : `fill="${TODO_COLORS[status]}"`
    return `<rect x="${x + 0.75}" y="${y + 0.75}" width="${CELL_PX - 1.5}" height="${CELL_PX - 1.5}" rx="2" ${paint}/>`
  })
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${BADGE_PX}" viewBox="0 0 ${width} ${BADGE_PX}">
${rects.join('\n')}
</svg>`
}
