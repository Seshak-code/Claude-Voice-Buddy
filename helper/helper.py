#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "numpy",
#   "sounddevice",
#   "pysilero-vad",
#   "mlx-whisper; sys_platform == 'darwin' and platform_machine == 'arm64'",
#   "mlx-audio; sys_platform == 'darwin' and platform_machine == 'arm64'",
#   "misaki[en]; sys_platform == 'darwin' and platform_machine == 'arm64'",
#   "faster-whisper; sys_platform != 'darwin' or platform_machine != 'arm64'",
#   "kokoro-onnx; sys_platform != 'darwin' or platform_machine != 'arm64'",
# ]
# ///
"""voice-buddy audio helper: always-on mic -> Silero + bandpass -> speech-to-text, and text-to-speech for replies.

Runs in the background (the plugin starts it); everything is local. It talks to the plugin only
through files in the state dir (default ~/.voice-buddy), so it behaves the same on every OS:
  state.json   written here, read by the plugin: state, mic, owner, utterances, log
  cmd/*.json   written by the plugin, consumed here: say | stop | mic | mute | unmute | claim | quit
  heartbeat    rewritten by the plugin every few seconds; this process exits when it goes stale
  alive        touched here every second; the launcher uses it to see whether we are running

Backends: Apple Silicon -> MLX Whisper + MLX Kokoro. Everywhere else -> faster-whisper + Kokoro (ONNX),
and the OS's own voice if Kokoro cannot load. Only macOS/Apple Silicon is tested.
"""
import argparse
import json
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from endpoint import FRAME, Endpointer
from speech_text import speakable

APPLE = sys.platform == "darwin" and platform.machine() == "arm64"
RATE = 16000
ECHO_TAIL = 0.4                  # seconds the mic stays deaf after Claude stops talking
HEARTBEAT_STALE = 25             # seconds without a heartbeat before we exit
VOICE = os.environ.get("VOICE_BUDDY_VOICE", "af_heart")
INPUT_DEVICE = os.environ.get("VOICE_BUDDY_INPUT_DEVICE") or None    # part of a device name; default: the system's
OUTPUT_DEVICE = os.environ.get("VOICE_BUDDY_OUTPUT_DEVICE") or None
MLX_WHISPER = "mlx-community/whisper-large-v3-turbo"
MLX_KOKORO = "mlx-community/Kokoro-82M-bf16"
KOKORO_ONNX_FILES = {          # downloaded once into the state dir
    "kokoro-v1.0.onnx": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
    "voices-v1.0.bin": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
}
# ponytail: Whisper hallucinates these on noise/silence; a fixed list is crude, a real VAD score gate is the upgrade.
HALLUCINATIONS = {"", "you", "amen", "thank you", "thanks for watching", "thank you for watching", "bye", "okay"}
NO_MIC = ("{device} is giving pure silence. If it's a headset, it may be off or not worn: put it on, or pick "
          "another mic with VOICE_BUDDY_INPUT_DEVICE. Otherwise the OS is blocking mic access for your terminal.")


# --- speech to text ------------------------------------------------------------------------------
_stt = None


def load_stt():
    global _stt
    import numpy as np
    if APPLE:
        import mlx_whisper
        mlx_whisper.transcribe(np.zeros(RATE, dtype=np.float32), path_or_hf_repo=MLX_WHISPER)  # warm-up / download
        _stt = lambda audio: [(s["text"], s.get("avg_logprob", 0), s.get("no_speech_prob", 0)) for s in
                              mlx_whisper.transcribe(audio, path_or_hf_repo=MLX_WHISPER, language="en")["segments"]]
        return
    from faster_whisper import WhisperModel
    # The big model is only worth it on a GPU; on CPU "small.en" keeps up with speech.
    import ctypes.util
    has_cuda = bool(ctypes.util.find_library("cudart") or ctypes.util.find_library("cudart64_12"))
    name = os.environ.get("VOICE_BUDDY_STT_MODEL", "large-v3-turbo" if has_cuda else "small.en")
    model = WhisperModel(name, device="cuda" if has_cuda else "cpu", compute_type="float16" if has_cuda else "int8")
    _stt = lambda audio: [(s.text, s.avg_logprob, s.no_speech_prob) for s in
                          model.transcribe(audio, language="en", beam_size=1)[0]]


def transcribe(audio) -> str:
    segs = _stt(audio)
    # Whisper's own confidence: noise turned into words scores low (-1 is its usual cutoff).
    if segs and all(no_speech > 0.6 or logprob < -1.0 for _, logprob, no_speech in segs):
        return ""
    text = " ".join(t.strip() for t, _, _ in segs).strip()
    return "" if re.sub(r"[^a-z ]", "", text.lower()).strip() in HALLUCINATIONS else text


# --- text to speech ------------------------------------------------------------------------------
def load_kokoro(state_dir: Path):
    """Returns synth(text) -> iterator of (float32 samples, sample_rate)."""
    if APPLE:
        from mlx_audio.tts.utils import load_model
        tts = load_model(MLX_KOKORO)
        list(tts.generate(text="Ready.", voice=VOICE, lang_code="a"))  # warm-up
        return lambda text: ((seg.audio, seg.sample_rate) for seg in tts.generate(text=text, voice=VOICE, lang_code="a"))
    from kokoro_onnx import Kokoro
    for name, url in KOKORO_ONNX_FILES.items():
        if not (state_dir / name).exists():
            urllib.request.urlretrieve(url, state_dir / (name + ".part"))
            (state_dir / (name + ".part")).replace(state_dir / name)
    tts = Kokoro(str(state_dir / "kokoro-v1.0.onnx"), str(state_dir / "voices-v1.0.bin"))
    return lambda text: iter([tts.create(text, voice=VOICE, speed=1.0, lang="en-us")])


def system_voice_cmd(text: str):
    """The OS's own speech command, used if Kokoro cannot load. Returns (argv, env) or None."""
    if sys.platform == "darwin":
        return ["say", text], None
    if sys.platform == "win32":
        ps = "Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak($env:VOICE_BUDDY_TEXT)"
        return ["powershell", "-NoProfile", "-Command", ps], {**os.environ, "VOICE_BUDDY_TEXT": text}
    for tool in ("espeak-ng", "espeak", "spd-say"):
        if shutil.which(tool):
            return [tool, text], None
    return None


class Speaker:
    """Speaks on its own thread; stop() cuts it off mid-sentence."""

    def __init__(self, state_dir: Path, note):
        self.synth = None
        try:
            self.synth = load_kokoro(state_dir)
        except Exception as err:
            note(f"Kokoro unavailable ({type(err).__name__}); using the system voice.")
        self.q = queue.Queue()
        self.gen = 0                      # bumped by stop() to abandon the current reply
        self.speaking = threading.Event()
        self.ended_at = 0.0
        threading.Thread(target=self._run, daemon=True).start()

    def say(self, text: str):
        self.q.put(text)

    def stop(self):
        self.gen += 1                     # _run checks this between 100 ms chunks
        while not self.q.empty():
            self.q.get_nowait()

    def deaf(self) -> bool:
        return self.speaking.is_set() or time.time() - self.ended_at < ECHO_TAIL

    def _run(self):
        import numpy as np
        import sounddevice as sd
        out, rate = None, None
        while True:
            text = self.q.get()
            mine = self.gen
            self.speaking.set()
            try:
                if self.synth is None:
                    self._speak_system(text, mine)
                    continue
                for audio, sample_rate in self.synth(text):
                    if out is None or rate != sample_rate:
                        # Blocking writes to one long-lived stream: no Python audio callback
                        # competing for the GIL (that crackled), and a roomy buffer.
                        out = sd.OutputStream(samplerate=sample_rate, channels=1, dtype="float32", latency="high", device=OUTPUT_DEVICE)
                        out.start()
                        rate = sample_rate
                    audio = np.asarray(audio, dtype=np.float32).reshape(-1, 1)
                    for i in range(0, len(audio), sample_rate // 10):
                        if self.gen != mine:
                            break
                        out.write(audio[i:i + sample_rate // 10])
                    if self.gen != mine:
                        break
            finally:
                self.ended_at = time.time()
                self.speaking.clear()

    def _speak_system(self, text: str, mine: int):
        cmd = system_voice_cmd(text)
        if not cmd:
            return
        proc = subprocess.Popen(cmd[0], env=cmd[1], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        while proc.poll() is None:
            if self.gen != mine:
                proc.terminate()
            time.sleep(0.05)


# --- the helper ----------------------------------------------------------------------------------
class Helper:
    def __init__(self, state_dir: Path, owner: str):
        self.dir = state_dir
        self.owner = owner
        self.started = time.time()
        self.speaker = None
        self.stream = None                # mic InputStream while unmuted
        self.ep = Endpointer()
        self.frames = queue.Queue()
        self.transcribing = False
        self.utterances, self.log, self.next_id = [], [], 1
        self.lock = threading.Lock()
        self.last_written = None

    # --- state file ---
    def state(self) -> str:
        if self.speaker is None:
            return "loading"
        if self.speaker.speaking.is_set():
            return "talking"
        if self.transcribing:
            return "thinking"
        if self.ep.hearing:
            return "hearing"
        return "listening" if self.stream else "off"

    def write_state(self, force=False):
        with self.lock:
            snap = {"state": self.state(), "mic": bool(self.stream), "owner": self.owner,
                    "utterances": self.utterances[-20:], "log": self.log[-10:]}
        if snap == self.last_written and not force:
            return
        self.last_written = snap
        tmp = self.dir / "state.json.tmp"
        tmp.write_text(json.dumps(snap))
        tmp.replace(self.dir / "state.json")          # atomic: the plugin never reads half a file

    def note(self, line: str):
        with self.lock:
            self.log.append(line)

    # --- mic ---
    def set_mic(self, on: bool):
        import sounddevice as sd
        if on and not self.stream:
            self.stream = sd.InputStream(samplerate=RATE, channels=1, dtype="int16", device=INPUT_DEVICE,
                                         blocksize=FRAME, callback=self._on_frame)
            self.stream.start()
        elif not on and self.stream:
            self.stream.stop(); self.stream.close(); self.stream = None
            self.frames.put(None)         # tell the listener to drop any half-heard utterance

    def _on_frame(self, data, *_):
        # Echo guard: drop the mic while Claude speaks (and briefly after).
        if not self.speaker.deaf():
            self.frames.put(bytes(data))

    def listen_forever(self):
        import numpy as np
        from pysilero_vad import SileroVoiceActivityDetector
        vad = SileroVoiceActivityDetector()
        zeros = 0
        while True:
            frame = self.frames.get()
            if frame is None:
                self.ep.reset()
                continue
            if not any(frame):
                zeros += 1
                if zeros == 100:          # 3 s of exact zeros: a headset not worn, or mic access blocked
                    import sounddevice as sd
                    self.note(NO_MIC.format(device=sd.query_devices(INPUT_DEVICE, kind="input")["name"]))
                continue
            zeros = 0
            utterance = self.ep.feed(frame, vad(frame))
            if utterance is None or not self.stream:
                continue
            audio = np.frombuffer(utterance, np.int16).astype(np.float32) / 32768
            if len(audio) >= RATE * 0.6:
                self.transcribing = True
                try:
                    text = transcribe(audio)
                finally:
                    self.transcribing = False
                if text:
                    with self.lock:
                        self.utterances.append({"id": self.next_id, "text": text})
                        self.next_id += 1
            with self.frames.mutex:       # anything heard while transcribing is stale
                self.frames.queue.clear()

    # --- commands (files dropped in cmd/ by the plugin) ---
    def poll_commands(self):
        cmd_dir = self.dir / "cmd"
        for path in sorted(cmd_dir.glob("*.json")) if cmd_dir.exists() else []:
            try:
                cmd = json.loads(path.read_text())
            except (OSError, ValueError):
                if time.time() - path.stat().st_mtime > 2:   # not just mid-write: junk, drop it
                    path.unlink(missing_ok=True)
                continue
            path.unlink(missing_ok=True)
            kind = cmd.get("cmd")
            if kind == "quit":
                self.exit()
            elif kind == "claim":
                self.owner = cmd.get("owner", "")
                self.write_state(force=True)
            elif self.speaker is None:
                continue                  # still loading
            elif kind == "say":
                text = speakable(cmd.get("text", ""))
                if text:
                    self.speaker.say(text)
            elif kind == "stop":
                self.speaker.stop()
            elif kind in ("mic", "mute", "unmute"):
                self.set_mic(not self.stream if kind == "mic" else kind == "unmute")

    def heartbeat_stale(self) -> bool:
        try:
            last = float((self.dir / "heartbeat").read_text()) / 1000
        except (OSError, ValueError):
            last = self.started
        return time.time() - max(last, self.started) > HEARTBEAT_STALE

    def run(self):
        threading.Thread(target=self.tick_forever, daemon=True).start()
        load_stt()
        self.speaker = Speaker(self.dir, self.note)
        threading.Thread(target=self.listen_forever, daemon=True).start()
        self.set_mic(True)                # listening from the start; the plugin's button mutes
        while not self.heartbeat_stale():
            time.sleep(0.5)
        self.exit()

    def exit(self):
        # Gone means gone: a lingering fresh `alive` would make the next start think we're still running.
        (self.dir / "alive").unlink(missing_ok=True)
        os._exit(0)

    def tick_forever(self):
        last_alive = 0.0
        while True:
            if time.time() - last_alive > 1:
                (self.dir / "alive").write_text(str(time.time()))
                last_alive = time.time()
            self.poll_commands()
            self.write_state()
            time.sleep(0.05)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", default=str(Path.home() / ".voice-buddy"))
    ap.add_argument("--owner", default="")
    args = ap.parse_args()
    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)

    try:                                  # single instance: a fresh `alive` file means one is running
        if time.time() - (state_dir / "alive").stat().st_mtime < 5:
            sys.exit(0)
    except OSError:
        pass

    sys.stderr = open(state_dir / "helper.log", "w", buffering=1)
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    Helper(state_dir, args.owner).run()


if __name__ == "__main__":
    main()
