// The animated buddy: an orange octopus that wears headphones while it listens and grabs a mic to talk.
// A frame is 7 rows: [left decor (2) | octopus (15) | right decor]. Glyphs pick their colour, so each part
// uses its own: body ▄▟█▙▝▜▛▘▚▞, headphones ┏━┓┃◖◗, mic ▁▓▔║().

export type BuddyState = 'loading' | 'off' | 'listening' | 'hearing' | 'thinking' | 'talking'

const HP_STATES = new Set<string>(['listening', 'hearing', 'thinking'])
const BAND = ' ┏━━━━━━━━━━━┓ '
const CUPS = ' ◖           ◗ '
const blank = (): string[] => Array(7).fill('')
const at = (row: number, text: string) => blank().map((_, i) => (i === row ? text : ''))

function octopus(eyes: string, mouth: string, hp: boolean, t: number, left = blank(), right = blank(), lifted = false) {
  const [l, r] = hp ? [' ◖', '◗ '] : ['  ', '  ']
  const legs = t % 4 < 2 ? '   ▚ ▞ ▚ ▞ ▚   ' : '   ▞ ▚ ▞ ▚ ▞   ' // wiggle
  const rows = [
    lifted ? BAND : '',
    hp ? BAND : lifted ? CUPS : '',
    hp ? ' ┃▄▟███████▙▄┃ ' : '  ▄▟███████▙▄  ',
    `${l}██ ${eyes} ██${r}`,
    `${l}██   ${mouth}   ██${r}`,
    '  ▝▜███████▛▘  ',
    legs,
  ]
  return rows.map((row, i) => `${left[i].padStart(2)}${row.padEnd(15)}${right[i]}`)
}

/** A hand-held mic on rows 3-6, `pad` columns right of the octopus. */
function mic(pad: number, before = '', after = '') {
  const sp = ' '.repeat(pad + before.length)
  return ['', '', '', `${sp} ▁▁▁`, `${' '.repeat(pad)}${before}(▓▓▓)${after}`, `${sp} ▔▔▔`, `${sp}  ║`]
}

export function draw(state: BuddyState, t: number): string[] {
  const eyes = t % 40 < 2 ? '─   ─' : '◕   ◕' // blink
  const slow = Math.floor(t / 6)
  switch (state) {
    case 'listening':
      return octopus(eyes, '‿', true, slow, blank(), at(1 + (slow % 2), slow % 2 ? ' ♪' : ' ♫'))
    case 'hearing':
      return octopus('◉   ◉', 'o', true, t, blank().map((_, i) => (i === 3 || i === 4 ? ['(', '(('][t % 2] : '')))
    case 'thinking':
      return octopus('◔   ◔', '~', true, slow, blank(), at(2, ' ' + '·'.repeat(1 + (Math.floor(t / 4) % 3))))
    case 'talking':
      return octopus(eyes, '◯▽─○'[Math.floor(t / 2) % 4], false, t, blank(), mic(0, '', ' ' + ')'.repeat(1 + (Math.floor(t / 2) % 3))))
    case 'off':
      return octopus('─   ─', '‿', false, 0, blank(), at(3 - (Math.floor(t / 8) % 3), ' ' + ['z', 'z Z', 'z Z z'][Math.floor(t / 8) % 3]))
    default: {
      const spin = '◐◓◑◒'[Math.floor(t / 3) % 4]
      return octopus(`${spin}   ${spin}`, '·', false, slow, blank(), at(3, ' booting…'))
    }
  }
}

/** Zippy in-between frames when the headphones swap for the mic (and back). */
export function transition(from: string, to: string): string[][] {
  if (to === 'talking' && HP_STATES.has(from)) {
    return [
      octopus('◉   ◉', 'o', false, 0, blank(), blank(), true),
      octopus('◠   ◠', '▽', false, 1, blank(), at(0, ' ≡≡┏━━┓')),
      octopus('◠   ◠', '▽', false, 2, blank(), at(0, '      ≡≡≡┏┓')),
      octopus('◕   ◕', '▽', false, 3, blank(), mic(4, '', '≡≡≡')),
      octopus('◕   ◕', '◯', false, 0, blank(), mic(0, '', ' ✦')),
    ]
  }
  if (from === 'talking' && HP_STATES.has(to)) {
    return [
      octopus('◕   ◕', '‿', false, 1, blank(), mic(3, '≡≡≡')),
      octopus('‿   ‿', '‿', false, 2, blank(), blank(), true),
      octopus('‿   ‿', '‿', true, 3, blank(), at(1, ' ✦')),
    ]
  }
  return []
}

/** The mute toggle's mic: struck through when muted. */
export function micIcon(isOn: boolean | null): string[] {
  return isOn === false ? [' ╲▁▁ ', '(▓╲▓)', ' ▔▔╲ ', '  ║ ╲'] : [' ▁▁▁ ', '(▓▓▓)', ' ▔▔▔ ', '  ║  ']
}

const PALETTE: [string, string][] = [
  ['▄▟█▙▝▜▛▘▚▞', '#D97757'], // octopus: Claude orange
  ['┏━┓┃◖◗', 'magenta'],
  ['()▁▓▔║', 'cyan'],
  ['♪♫·≡✦', 'yellow'],
  ['zZ', 'blue'],
  ['╲', 'red'],
]
const COLORS = new Map(PALETTE.flatMap(([chars, color]) => [...chars].map(c => [c, color] as const)))

export type Segment = { text: string; color?: string }

/** Splits a line into runs of one colour, one Text each. */
export function segments(line: string): Segment[] {
  const out: Segment[] = []
  for (const ch of line) {
    const color = COLORS.get(ch)
    const last = out.at(-1)
    if (last && last.color === color) last.text += ch
    else out.push({ text: ch, color })
  }
  return out
}
