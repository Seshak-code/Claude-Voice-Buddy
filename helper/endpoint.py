"""Split a stream of 32 ms mic frames into utterances: start when you talk, end when you pause.

A frame counts as speech only if BOTH:
  - Silero VAD says it's a voice (webrtcvad called 96% of a normal room "speech"; Silero, 0.2%), and
  - it is clearly louder than the room in the 300 Hz-4 kHz speech band. That bandpass ignores fan
    rumble entirely, and muffled speech from another room (which has lost its highs) stays quiet.

Run `python3 endpoint.py` for the self-check.
"""
from collections import deque

import numpy as np

RATE = 16000
FRAME = 512          # 32 ms, the chunk size Silero wants at 16 kHz
PRE_ROLL = 10        # frames kept from just before speech starts (320 ms)
START = 5            # speech frames out of the last PRE_ROLL that start an utterance
END_SILENCE = 25     # non-speech frames that end an utterance (~800 ms pause)
MAX_FRAMES = 1875    # hard cap (~60 s) so one utterance can't run forever
MIN_SPEECH = 14      # utterances with less than ~0.45 s of actual speech are noise, dropped
VOICE_PROB = 0.5     # Silero threshold
LOUDER = 2.5         # speech-band level must be this many times the room's...
MIN_BAND = 60        # ...and at least this (measured: room ~35-45, a voice ~255)
BAND = (300, 4000)   # Hz

_freqs = np.fft.rfftfreq(FRAME, 1 / RATE)
_in_band = (_freqs >= BAND[0]) & (_freqs <= BAND[1])
_window = np.hanning(FRAME)
_norm = 2 / (FRAME * (_window ** 2).sum())


def band_level(frame: bytes) -> float:
    """RMS of the frame after an FFT bandpass to the speech band."""
    samples = np.frombuffer(frame, np.int16).astype(np.float32)
    spectrum = np.abs(np.fft.rfft(samples * _window)) ** 2
    return float(np.sqrt(spectrum[_in_band].sum() * _norm))


class Endpointer:
    def __init__(self):
        # ponytail: room level = 20th percentile of the last 3 s of speech-band levels (speech has
        # enough gaps that p20 stays near the room, so it keeps adapting mid-utterance).
        self.background = deque(maxlen=94)
        self.reset()

    def reset(self):
        self.ring, self.utterance, self.silent, self.spoken = [], None, 0, 0

    @property
    def hearing(self) -> bool:
        return self.utterance is not None

    def feed(self, frame: bytes, voice_prob: float) -> bytes | None:
        """Returns the whole utterance (int16 bytes) when it ends, else None."""
        level = band_level(frame)
        floor = np.percentile(self.background, 20) if len(self.background) >= 30 else None
        speech = floor is not None and voice_prob > VOICE_PROB and level > max(LOUDER * floor, MIN_BAND)
        self.background.append(level)

        if self.utterance is None:
            self.ring = (self.ring + [(frame, speech)])[-PRE_ROLL:]
            if sum(s for _, s in self.ring) >= START:
                self.utterance, self.silent = [f for f, _ in self.ring], 0
            return None

        self.utterance.append(frame)
        self.spoken += speech
        self.silent = 0 if speech else self.silent + 1
        if self.silent < END_SILENCE and len(self.utterance) < MAX_FRAMES:
            return None
        done = b"".join(self.utterance) if self.spoken >= MIN_SPEECH else None
        self.reset()
        return done


if __name__ == "__main__":
    rng = np.random.default_rng(0)
    t = np.arange(FRAME) / RATE

    def noise(seconds, level):
        return [rng.normal(0, level, FRAME).astype(np.int16).tobytes() for _ in range(int(seconds / 0.032))]

    def hum(seconds, amp, hz=90):   # fan/AC rumble below the speech band
        return [(amp * np.sin(2 * np.pi * hz * (t + i * FRAME / RATE))).astype(np.int16).tobytes()
                for i in range(int(seconds / 0.032))]

    # Worst case: the VAD is fooled (prob 1.0) and only the bandpass/loudness gate decides.
    ep = Endpointer()
    for f in noise(0.5, 5) + noise(4, 200):          # mic warm-up, then the room
        ep.feed(f, 1.0)
    assert not ep.hearing, "stuck hearing after mic warm-up"

    ep = Endpointer()
    assert not any(ep.feed(f, 1.0) for f in noise(3, 60)), "room noise started an utterance"
    assert not any(ep.feed(f, 1.0) for f in hum(3, 6000)) and not ep.hearing, "loud fan hum counted as speech"
    assert not any(ep.feed(f, 1.0) for f in noise(1.5, 2000)), "ended while still talking"
    assert ep.hearing
    out = [u for u in (ep.feed(f, 0.0) for f in noise(1.2, 60)) if u]
    assert len(out) == 1, "pause after speaking did not end the utterance"
    seconds = len(out[0]) / 2 / RATE
    assert 1.5 < seconds < 3, seconds
    assert not ep.hearing
    assert not any(ep.feed(f, 1.0) for f in noise(0.3, 3000) + noise(1.2, 60)), "short bang was sent"
    # And with the real VAD saying "not a voice", loud noise never starts anything.
    assert not any(ep.feed(f, 0.1) for f in noise(2, 3000)) and not ep.hearing, "non-voice noise started an utterance"
    print(f"ok: room, fan hum, bangs and non-voice noise ignored; speech captured ({seconds:.1f}s); pause ended it")
