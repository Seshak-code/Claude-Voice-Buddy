# Claude Voice Buddy

Talk to Claude Code and hear it answer. Speak, pause, and your words are sent as a prompt; Claude's reply is read back to you. A small animated buddy in a side pane shows what's happening: headphones on while it listens, a mic when Claude talks.

Everything runs on your own machine. No audio or text is sent anywhere by this plugin. [What it does on your machine](#what-this-plugin-does-on-your-machine) lists every program, file and download.

## Install

```
/plugin install voice-buddy --marketplace Seshak-code/Claude-Voice-Buddy
```

Then type `/buddy` in any Claude Code session. (Not `/voice`: that's Claude Code's own built-in dictation.)

**Needs:** [uv](https://docs.astral.sh/uv/) on your PATH (it provides Python and the audio libraries), a microphone, and speakers or headphones. On Linux, PortAudio too (`sudo apt install libportaudio2`).

## Use

| Command | What it does |
| --- | --- |
| `/buddy` or `/buddy on` | Start listening and open the pane. Stays on for future sessions until `/buddy off`. |
| `/buddy mute` / `/buddy unmute` | Mute or unmute the mic (or press the pane's mic button, or `m` while the pane is focused). |
| `/buddy pane` | Reopen the pane. |
| `/buddy off` | Stop everything. |

Just talk; when you pause for about a second, it transcribes and sends. While Claude speaks the mic is ignored so it doesn't hear itself. Typing or speaking a new prompt cuts off the current reply. Code, paths and links are not read aloud ("code on screen" instead), and very long replies are cut short, with the rest left on screen.

The first `/buddy` downloads the speech models (a few GB) and can take several minutes. Later starts take seconds.

## How it works

The plugin (`hooks/`) draws the pane, submits what you said as a prompt, and hands Claude's final reply to be spoken. The audio work runs in a separate local process (`helper/helper.py`), which the plugin starts with `/buddy`. It stops when the session ends, or on its own about 20 seconds after Claude Code goes away. The two talk only through files in the plugin's own `.state/` folder.

| Step | Apple Silicon Macs | Everything else |
| --- | --- | --- |
| Is someone speaking? | Silero VAD + a 300 Hz–4 kHz bandpass loudness gate (ignores fans and muffled speech from other rooms) | same |
| Speech to text | Whisper large-v3-turbo on MLX | faster-whisper (`small.en` on CPU, `large-v3-turbo` with CUDA; set `VOICE_BUDDY_STT_MODEL` to change) |
| Text to speech | Kokoro on MLX | Kokoro (ONNX); falls back to the OS voice (`say`, Windows SAPI, `espeak-ng`/`spd-say`) |

Settings (environment variables): `VOICE_BUDDY_INPUT_DEVICE` and `VOICE_BUDDY_OUTPUT_DEVICE` (part of a device name, e.g. `MacBook`; default: the system's), `VOICE_BUDDY_VOICE` (Kokoro voice, default `af_heart`).

If the pane says your mic is giving pure silence, the usual cause is a headset (AirPods) that's connected but not worn.

**Tested on** macOS, Apple Silicon. The Windows, Linux and Intel paths are written but not yet tested.

## What this plugin does on your machine

### Programs it runs, and why

The plugin runs one command, from its own folder, only when you turn voice on (`/buddy`), or at session start if you left it on:

```
uv run --locked --script helper/launch.py start
```

- **`uv`** supplies Python and installs the helper's audio libraries, at the exact versions in the committed `helper/*.py.lock` files (`--locked`).
- **`helper/launch.py`** (standard library only) starts the audio helper in the background, unless one is already running: `uv run --locked --script <plugin>/helper/helper.py --state-dir <plugin>/.state`.
- **`helper/helper.py`** listens to the microphone, turns speech into text, and speaks replies. On non-Apple machines, if Kokoro can't load, it runs the OS's own speech program for replies: `say` (macOS), PowerShell's System.Speech (Windows), or `espeak-ng`, `espeak` or `spd-say` (Linux).

The plugin then writes a `claim` command file holding a random ID it made for this session, so the helper knows which session gets the transcripts.

### Files it reads and writes

Everything is in `<plugin>/.state/` (the plugin's own folder). The plugin doesn't edit any build, start-up, settings or instruction file.

| File | Written by | Read by | Holds |
| --- | --- | --- | --- |
| `state.json` | helper | plugin | the buddy's state, mic on/off, the session that owns the helper, the last 20 transcripts, the last 10 notices |
| `cmd/*.json` | plugin | helper (then deleted) | commands: `say` (with Claude's reply), `stop`, `mic`, `mute`, `unmute`, `claim` (with the session ID), `quit` |
| `heartbeat` | plugin, every ~5 s | helper | a timestamp; the helper exits when it goes stale |
| `alive` | helper, every second | plugin, launcher | a timestamp, so nothing starts a second helper |
| `helper.log`, `helper.out` | helper | you | errors and warnings |

Model files go to the usual caches: Hugging Face's (`~/.cache/huggingface`), and on non-Apple machines `~/.cache/voice-buddy` for Kokoro ONNX. Claude Code's plugin storage keeps one value: whether voice was left on (`autostart`).

The plugin reads no secrets, keys or settings from your machine. The helper reads only its own environment variables (`VOICE_BUDDY_*`, above) and hands no environment to any program it starts.

### What it sends, and where

See also the [privacy policy](PRIVACY.md).


- **The plugin's hooks make no network calls.** They only read and write the files above and run the command above.
- **Your microphone audio never leaves your machine.** It's processed in memory and never saved.
- **Downloads, on first use only:**
  - Python packages from PyPI, through uv
  - Speech models from Hugging Face (`huggingface.co`): Whisper and Kokoro, and on non-Apple machines faster-whisper's models
  - On non-Apple machines, the Kokoro ONNX files from GitHub releases (`github.com/thewh1teagle/kokoro-onnx`)
  - On Apple Silicon, a small English language model from GitHub (`github.com/explosion/spacy-models`), which Kokoro uses

  Nothing about you or your conversation is sent in these requests.
- **Your prompts and Claude's replies** go only where Claude Code already sends them.

Where each piece of data goes, end to end:

- **Your speech:** microphone → helper (in memory) → text in `.state/state.json` → read by the plugin → submitted as your prompt. That's the only thing the plugin reads from a file and puts in a prompt.
- **Claude's final reply:** read by the `turn.complete` hook → written to `.state/cmd/*.json` → spoken by the helper → file deleted. It goes nowhere else.
- **The command the plugin runs** gets no data at all: it's fixed text, with no arguments from the conversation or from files.
- **The `prompt.submit` hook** doesn't read or keep your prompt; it only tells the helper to stop speaking.

### What it puts in prompts

- **Prompts it submits:** exactly the words you said, as transcribed. Nothing is added.
- **System prompt:** while voice is on, one section is added: *"The user is talking to you by voice: their messages are speech transcripts (expect misheard identifiers), and your final message is read aloud. Keep final messages short and conversational; leave code, diffs and long lists on screen and just say what they are."*

### Hooks

| Hook | What it does | What it changes |
| --- | --- | --- |
| `session.start` | Registers `/buddy`; if voice was left on, turns it on and opens the pane | nothing |
| `command.run` (`/buddy`) | Turns voice on or off, mutes or unmutes, opens the pane | nothing else |
| `prompt.submit` | Tells the helper to stop speaking (you're talking or typing again) | nothing: the prompt goes on unchanged |
| `turn.complete` | Hands Claude's final answer to the helper to speak (main conversation only, not subagents) | nothing: the answer is shown unchanged |
| `prompt.compose` | Adds the voice section above to the system prompt, while voice is on | adds that one section |
| `session.end` | Tells the helper to quit | nothing |
| `ui.render` (its own pane) | Draws the buddy, the mute button and the last few lines | only its own pane |

The plugin also declares a type contract (`types` in `plugin.json`) so `claude plugin validate` can check the pane's state; Claude Code ignores it when loading.

## Develop

```
claude --plugin-dir .            # run a session with this folder loaded
claude plugin validate .
claude plugin test .             # buddy animation checks
npx tsc -p .                     # type-check (after the plugin has loaded once, which lays its types)
uv run --no-project --with numpy python helper/endpoint.py   # speech detector checks
python3 helper/speech_text.py                      # reply clean-up checks
```

## Credits

[Whisper](https://github.com/openai/whisper) (MIT), [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (MIT), [MLX](https://github.com/ml-explore/mlx) (MIT), [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M) (Apache 2.0), [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) (MIT), [Silero VAD](https://github.com/snakers4/silero-vad) (MIT).
