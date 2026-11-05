// The band's colours, one set for every part that draws one.
import type { DebriefTodoStatus } from '../types'

export const COLORS = { green: '#10b981', indigo: '#6366f1', amber: '#f59e0b', red: '#ef4444', grey: '#9ca3af', white: '#ffffff' } as const

// Text takes the theme key nearest each colour, so it darkens on a light theme and lightens on a dark one; a drawing
// keeps the hex, which reads on either.
const THEME_KEYS: Record<string, string> = {
  [COLORS.green]: 'success',
  [COLORS.indigo]: 'permission',
  [COLORS.amber]: 'warning',
  [COLORS.red]: 'error',
  [COLORS.grey]: 'inactive',
}

export const textColorOf = (color: string): string => THEME_KEYS[color] ?? color

// An ask's number goes from indigo to red as it waits more turns.
const AGE_COLORS = [COLORS.indigo, COLORS.amber, '#f38a1d', '#f2702a', '#f05f37', COLORS.red]

export function ageColor(age: number): string {
  return AGE_COLORS[Math.min(age, AGE_COLORS.length - 1)] ?? COLORS.red
}

export const TODO_COLORS: Record<DebriefTodoStatus, string> = { done: COLORS.green, active: COLORS.indigo, open: COLORS.grey, blocked: COLORS.red }
