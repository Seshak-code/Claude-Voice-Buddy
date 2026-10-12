export type VoiceView = {
  /** The buddy's current 7-row frame. */
  frame: string[]
  /** Short status under the buddy ("listening…"). */
  label: string
  /** Mic on (true), muted (false), or the helper still starting (null). */
  mic: boolean | null
  /** The last few lines of conversation and notices. */
  log: string[]
}

declare module 'claude-code' {
  interface PluginState {
    'voice-buddy': { view: VoiceView }
  }
}
