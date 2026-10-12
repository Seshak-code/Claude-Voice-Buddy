# Claude Voice Buddy

Talk to Claude Code and hear it answer. Speak, pause, and your words are sent as a prompt; Claude's reply is read back to you. A small animated buddy in a side pane shows what's happening: headphones on while it listens, a mic when Claude talks.

Everything runs on your own machine. No audio or text is sent anywhere by this plugin.

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

The plugin (hooks in `hooks/`) draws the pane, submits what you said as a prompt, sends Claude's final reply to be spoken, and adds a short system-prompt note asking Claude to keep spoken replies brief.

The audio work runs in a separate local process (`helper/helper.py`), which the plugin starts on `/buddy` and stops when the session ends, or which stops itself about 20 seconds after Claude Code goes away. They talk only through files in `~/.voice-buddy/`.

| Step | Apple Silicon Macs | Everything else |
| --- | --- | --- |
| Is someone speaking? | Silero VAD + a 300 Hz–4 kHz bandpass loudness gate (ignores fans and muffled speech from other rooms) | same |
| Speech to text | Whisper large-v3-turbo on MLX | faster-whisper (`small.en` on CPU, `large-v3-turbo` with CUDA; set `VOICE_BUDDY_STT_MODEL` to change) |
| Text to speech | Kokoro on MLX | Kokoro (ONNX); falls back to the OS voice (`say`, Windows SAPI, `espeak-ng`/`spd-say`) |

Settings (environment variables): `VOICE_BUDDY_INPUT_DEVICE` and `VOICE_BUDDY_OUTPUT_DEVICE` (part of a device name, e.g. `MacBook`; default: the system's), `VOICE_BUDDY_VOICE` (Kokoro voice, default `af_heart`), `VOICE_BUDDY_DIR` (state folder).

If the pane says your mic is giving pure silence, the usual cause is a headset (AirPods) that's connected but not worn.

**Tested on** macOS, Apple Silicon. The Windows, Linux and Intel paths are written but not yet tested.

## Privacy and network use

- **Microphone:** while voice is on and not muted, the helper listens to your microphone continuously, to detect speech. Audio is processed in memory and never saved or sent anywhere.
- **What's stored:** `~/.voice-buddy/` holds the current state, the last few transcripts (so the plugin can pick them up), logs and downloaded model files. Delete the folder at any time.
- **Network:** only to download models and packages on first use:
  - Python packages through uv (PyPI)
  - Speech models from Hugging Face (`huggingface.co`): Whisper, Kokoro, and on non-Apple machines faster-whisper's models
  - On non-Apple machines, Kokoro ONNX files from GitHub releases (`github.com/thewh1teagle/kokoro-onnx`)
  - On Apple Silicon, a small English language model from GitHub (`github.com/explosion/spacy-models`), used by Kokoro
- **Your prompts and Claude's replies** go only where Claude Code already sends them. The plugin adds nothing.

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
