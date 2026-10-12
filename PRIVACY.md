# Privacy policy: Claude Voice Buddy

Effective 11 October 2026.

Claude Voice Buddy (the `voice-buddy` plugin for Claude Code) runs entirely on your own computer. Its author collects nothing: there is no account, no analytics, no telemetry and no server.

## What it uses

- **Your microphone**, only while voice is on (`/buddy`) and not muted. Audio is turned into text in memory on your computer, then discarded. It's never recorded, saved or sent anywhere.
- **The text of what you said**, which it submits to Claude Code as your prompt, exactly like typing it.
- **Claude's final reply**, which it reads aloud on your computer.

## What it stores

Only on your computer, in the plugin's own `.state/` folder: its current state, the last 20 transcripts (so the plugin can pick them up), short-lived commands, and logs. Speech models are kept in your usual model caches (`~/.cache/huggingface`, and `~/.cache/voice-buddy` on non-Apple computers). Delete any of these at any time; `/buddy off` stops everything.

## What leaves your computer

- **Your prompts and Claude's replies** go only where Claude Code already sends them, under Anthropic's terms. The plugin adds a short note to Claude's system prompt asking for brief, speakable replies, and adds nothing to your prompts.
- **First-use downloads:** Python packages (PyPI, through uv) and speech models (Hugging Face; GitHub for some files). These are ordinary downloads that send nothing about you or your conversation, though those services see the request as any website would.

## Contact

Questions or concerns: open an issue at https://github.com/Seshak-code/Claude-Voice-Buddy/issues.
