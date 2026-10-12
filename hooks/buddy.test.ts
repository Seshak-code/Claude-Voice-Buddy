import { expect, test } from 'claude-code/testing'

import { draw, micIcon, segments, transition } from './buddy'
import type { BuddyState } from './buddy'

const STATES: BuddyState[] = ['loading', 'off', 'listening', 'hearing', 'thinking', 'talking']
const MAX_WIDTH = 30 // the side pane is 32 columns wide, less padding

test('every buddy frame has 7 rows that fit the pane', () => {
  const frames = [
    ...STATES.flatMap(s => [0, 5, 13, 40].map(t => draw(s, t))),
    ...transition('listening', 'talking'),
    ...transition('talking', 'listening'),
  ]
  expect(frames.length).toBeGreaterThan(24)
  for (const f of frames) {
    expect(f.length).toBe(7)
    for (const row of f) expect([...row].length).toBeLessThanOrEqual(MAX_WIDTH)
  }
})

test('the mic swaps in only around headphone states, and muted draws a strike', () => {
  expect(transition('off', 'listening')).toEqual([])
  expect(transition('listening', 'talking').length).toBe(5)
  expect(transition('talking', 'hearing').length).toBe(3)
  expect(micIcon(false).join('')).toContain('╲')
  expect(micIcon(true).join('')).not.toContain('╲')
  expect(segments('┏━ zz').map(s => s.color)).toEqual(['magenta', undefined, 'blue'])
})
