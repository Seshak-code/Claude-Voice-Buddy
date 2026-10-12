import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { VoiceView } from '../types'
import { draw, micIcon, segments, transition } from './buddy'
import type { BuddyState } from './buddy'

type Api = EngineInterface

const PANE = 'voice-buddy'
const TICK_MS = 150
const HEARTBEAT_EVERY = 33 // ticks, about 5 s; the helper quits if it stops hearing this
const RESTART_EVERY = 40 // ticks, about 6 s: while no helper of ours answers, check it's running and start it if not
const OFF_VIEW: VoiceView = { frame: draw('off', 0), label: 'voice is off, type /buddy', mic: null, log: [] }
const view = atom({ plugin: 'voice-buddy', key: 'view' } as const, OFF_VIEW)

const VOICE_PROMPT =
  'The user is talking to you by voice: their messages are speech transcripts (expect misheard identifiers), ' +
  'and your final message is read aloud. Keep final messages short and conversational; leave code, diffs ' +
  'and long lists on screen and just say what they are.'

const LABELS: Record<BuddyState, string> = {
  loading: 'starting up…',
  off: 'muted',
  listening: 'listening…',
  hearing: 'hearing you…',
  thinking: 'transcribing…',
  talking: 'talking',
}

type Helper = {
  state: BuddyState
  mic: boolean
  owner: string
  utterances: { id: number; text: string }[]
  log: string[]
}

// Plain module state: a reload starts these over, the helper itself keeps running.
const S = {
  isActive: false,
  dir: '',
  token: '',
  lastId: -1,
  ticks: 0,
  shown: 'loading' as BuddyState,
  queued: [] as string[][],
  seq: 0,
  signature: '',
  waiting: 0, // ticks since the helper last answered as ours
  inUseElsewhere: false,
  timer: undefined as { cancel: () => void } | undefined,
  chat: [] as string[],
}

const launchPy = ($: Api) => `${$.plugin.root}/helper/launch.py`

// `uv run --script` runs the stdlib-only launcher on any OS, with a Python it provides itself.
const uv = ($: Api, ...args: string[]) => $.process.run(['uv', 'run', '--no-project', '--script', ...args])

const remember = (line: string) => S.chat.splice(0, S.chat.push(line) - 5) // keep the last 5

// Commands to the helper are small files it picks up in name order: no shell, socket or lock, so any OS works.
const command = ($: Api, cmd: Record<string, unknown>) =>
  $.fs.write(`${S.dir}/cmd/${Date.now()}-${String(S.seq++).padStart(4, '0')}.json`, JSON.stringify(cmd))

async function tick($: Api) {
  S.ticks += 1
  if (S.ticks % HEARTBEAT_EVERY === 1) await $.fs.write(`${S.dir}/heartbeat`, String(Date.now()))
  // null: not written yet, or caught mid-replace; the next tick tries again
  const helper: Helper | null = await $.fs.read(`${S.dir}/state.json`).then(JSON.parse).catch(() => null)
  const isMine = helper !== null && helper.owner === S.token // a stale file or another session's helper isn't ours

  if (isMine) {
    if (S.lastId < 0) S.lastId = Math.max(0, ...helper.utterances.map(u => u.id)) // what was said before we joined is old news
    for (const u of helper.utterances) {
      if (u.id <= S.lastId) continue
      S.lastId = u.id
      remember(`you: ${u.text}`)
      $.prompt.submit({ text: u.text }).catch(() => {})
    }
  }

  S.waiting = isMine ? 0 : S.waiting + 1
  if (S.waiting > 0 && S.waiting % RESTART_EVERY === 0) await recover($, helper)

  const want: BuddyState = isMine ? helper.state : 'loading'
  if (want !== S.shown && S.queued.length === 0) {
    S.queued = transition(S.shown, want)
    S.shown = want
  }
  const frame = S.queued.shift() ?? draw(S.shown, S.ticks)
  const notices = isMine ? helper.log.slice(-2).map(l => `! ${l}`) : []
  const log = [...S.chat, ...notices].slice(-6)
  const mic = isMine && helper.state !== 'loading' ? helper.mic : null // the mic isn't open until the models load

  const label = S.inUseElsewhere && !isMine ? 'in use by another Claude session (/buddy to take it)' : LABELS[S.shown]

  const next = frame.join('|') + label + mic + log.join('|')
  if (next === S.signature) return
  S.signature = next
  await update($, view, () => ({ frame, label, mic, log }))
}

// No helper of ours is answering: start one if none is alive; if another session's is, say so rather than steal it.
async function recover($: Api, helper: Helper | null) {
  const alive = await $.fs.stat(`${S.dir}/alive`).catch(() => undefined)
  const isAlive = alive !== undefined && Date.now() - alive.mtimeMs < 5000
  S.inUseElsewhere = isAlive && helper !== null && helper.state !== 'loading'
  if (!isAlive) await uv($, launchPy($), 'start', S.token).catch(() => undefined)
}

async function activate($: Api): Promise<string> {
  if (S.isActive) {
    await command($, { cmd: 'claim', owner: S.token }) // /buddy again takes the helper back from another session
    S.inUseElsewhere = false
    return 'Voice is on.'
  }
  try {
    S.dir = (await uv($, launchPy($), 'where')).stdout.trim()
    S.token = Math.random().toString(36).slice(2)
    await $.fs.write(`${S.dir}/heartbeat`, String(Date.now()))
    await command($, { cmd: 'claim', owner: S.token }) // takes over a helper that is already running
    await uv($, launchPy($), 'start', S.token) // starts one otherwise
  } catch {
    return 'voice-buddy needs uv on your PATH: https://docs.astral.sh/uv/'
  }
  S.isActive = true
  S.lastId = -1
  S.timer = $.clock.every(TICK_MS, () => tick($))
  await $.store.set('autostart', true)
  return 'Voice is on. The first start downloads the speech models (a few GB) and can take a few minutes.'
}

async function deactivate($: Api): Promise<string> {
  if (!S.isActive) return 'Voice is already off.'
  S.isActive = false
  S.timer?.cancel()
  await command($, { cmd: 'quit' })
  await $.store.set('autostart', false)
  await update($, view, () => OFF_VIEW)
  return 'Voice is off.'
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    // Not /voice: that's Claude Code's own built-in command, and plugins can't (and shouldn't) take it over.
    await $.command
      .register({
        name: 'buddy',
        description: 'Talk to Claude and hear it answer: /buddy [on|off|mute|unmute|pane]',
        argumentHint: '[on|off|mute|unmute|pane]',
      })
      .catch(() => $.ui.toast('voice-buddy: could not register /buddy'))
    if ((await $.store.get('autostart')) === true) {
      await activate($)
      void $.ui.open({ id: PANE, title: 'Voice' }) // placed now on a wide terminal; /buddy pane otherwise
    }

    return next(e)
  })

  on('command.run', { command: 'buddy' }, async ($, e) => {
    const arg = e.args.trim().toLowerCase()
    if (arg === 'off') return { text: await deactivate($) }
    if ((arg === 'mute' || arg === 'unmute') && S.isActive) {
      await command($, { cmd: arg })
      return { text: arg === 'mute' ? 'Mic muted.' : 'Mic on.' }
    }
    const said = arg === 'pane' ? '' : await activate($)
    await $.ui.open({ id: PANE, title: 'Voice' })

    return { text: said || 'Voice pane opened.' }
  })

  on('prompt.submit', async ($, e, next) => {
    if (S.isActive) command($, { cmd: 'stop' }).catch(() => {}) // you spoke or typed: cut off whatever is being read

    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    if (S.isActive && e.agentId === undefined && !e.isAborted && e.answer.trim() !== '') {
      remember(`claude: ${e.answer.replace(/\s+/g, ' ').slice(0, 90)}`)
      command($, { cmd: 'say', text: e.answer }).catch(() => {})
    }

    return next(e)
  })

  on('prompt.compose', async ($, e, next) => {
    const composed = await next(e)
    if (!S.isActive) return composed

    return { sections: [...composed.sections, { id: 'voice-buddy:style', text: VOICE_PROMPT, scope: 'session' as const }] }
  })

  on('session.end', async ($, e, next) => {
    if (S.isActive) await command($, { cmd: 'quit' })
    S.timer?.cancel()

    return next(e)
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Button, Text } = $.ui.resolve(e)
    const v = await read($, view)
    const row = (line: string) => (
      <Box>
        {segments(line || ' ').map(s => (
          <Text color={s.color}>{s.text}</Text>
        ))}
      </Box>
    )

    return (
      <Box flexDirection="column">
        {v.frame.map(row)}
        <Text bold>{v.label}</Text>
        {micIcon(v.mic).map(row)}
        <Button
          key="mic"
          label={v.mic === null ? 'Starting…' : v.mic ? 'Mute  (m)' : 'Unmute  (m)'}
          hotkey="m"
          onPress={() => command($, { cmd: 'mic' })}
        />
        {v.log.length === 0 && <Text dimColor>Just talk; pause and it sends.</Text>}
        {v.log.map(line => (
          <Text dimColor wrap="wrap">
            {line}
          </Text>
        ))}
      </Box>
    )
  })
}
