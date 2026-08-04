"""8-bit style synthesis. Needs numpy; needs **no ffmpeg**.

Why no ffmpeg here
------------------
A waveform is just an array of numbers: ``sin()`` evaluated over time already
*is* audio, and the WAV container is a 44-byte header from the standard
library. That is why sound can be built in pure Python while video cannot --
H.264/AAC are patent-encumbered codecs with six-figure line counts.

Output formats, in preference order:

* **silk** -- QQ's native voice codec, ~5x smaller than WAV. Needs
  ``graiax-silkcoder``, which ships its own encoder (still no ffmpeg).
* **wav** -- always available. The official docs list ``silk/wav/mp3/flac``
  as accepted for ``file_type=3``, so this is a real fallback, not a hack.
"""
from __future__ import annotations

import io
import wave
from dataclasses import dataclass

from .theory import midi_to_hz

try:
    import numpy as np

    HAVE_NUMPY = True
except ImportError:  # pragma: no cover - exercised via the pure-Python path
    # numpy is not an AstrBot dependency and its wheel can be unavailable on
    # unusual platforms. Synthesis is simple arithmetic over a flat buffer, so
    # a pure-Python fallback costs some speed and nothing else -- far better
    # than a plugin that refuses to install.
    from . import _purepy as np  # type: ignore[no-redef]

    HAVE_NUMPY = False

#: 32 kHz mono. Chiptune waveforms are harmonically rich, so dropping to a
#: telephone rate makes square waves buzz; 32k is the cheapest rate that still
#: sounds like the note it claims to be.
SAMPLE_RATE = 32000

WAVEFORMS = {
    "square": "方波",
    "saw": "锯齿波",
    "triangle": "三角波",
    "sine": "正弦波",
}
DEFAULT_WAVEFORM = "square"

#: Peak level. Left below 1.0 so summing several notes does not clip.
HEADROOM = 0.82


def oscillator(waveform: str, freq: float, frames: int,
               sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """One cycle-accurate waveform of ``frames`` samples."""
    if frames <= 0:
        return np.zeros(0)
    t = np.arange(frames) / sample_rate
    if waveform == "square":
        return np.sign(np.sin(2 * np.pi * freq * t))
    if waveform == "saw":
        return 2.0 * ((freq * t) % 1.0) - 1.0
    if waveform == "triangle":
        return 2.0 * np.abs(2.0 * ((freq * t) % 1.0) - 1.0) - 1.0
    if waveform == "sine":
        return np.sin(2 * np.pi * freq * t)
    raise ValueError(f"未知波形：{waveform}")


def noise(frames: int, seed: int = 0) -> np.ndarray:
    """White noise -- the fourth classic chiptune voice, used for drums."""
    if frames <= 0:
        return np.zeros(0)
    return np.random.default_rng(seed).uniform(-1.0, 1.0, frames)


@dataclass(frozen=True, slots=True)
class Envelope:
    """ADSR in seconds (sustain is a level, not a time).

    Without an envelope a square wave starts and stops on a discontinuity,
    which is heard as a loud click on every note -- far more objectionable
    than the note itself.
    """

    attack: float = 0.006
    decay: float = 0.09
    sustain: float = 0.62
    release: float = 0.18


def apply_envelope(signal: np.ndarray, envelope: Envelope,
                   sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    frames = len(signal)
    if frames == 0:
        return signal
    curve = np.ones(frames)
    attack = min(int(envelope.attack * sample_rate), frames)
    decay = min(int(envelope.decay * sample_rate), max(0, frames - attack))
    release = min(int(envelope.release * sample_rate), frames)

    if attack:
        curve[:attack] = np.linspace(0.0, 1.0, attack)
    if decay:
        curve[attack:attack + decay] = np.linspace(1.0, envelope.sustain, decay)
    body_end = max(attack + decay, frames - release)
    curve[attack + decay:body_end] = envelope.sustain
    if release:
        curve[frames - release:] = np.linspace(
            curve[max(0, frames - release - 1)], 0.0, release)
    return signal * curve


def render_notes(
    notes: list[int],
    duration: float,
    waveform: str = DEFAULT_WAVEFORM,
    envelope: Envelope | None = None,
    sample_rate: int = SAMPLE_RATE,
) -> np.ndarray:
    """Sound all ``notes`` together for ``duration`` seconds."""
    frames = int(duration * sample_rate)
    if frames <= 0 or not notes:
        return np.zeros(0)
    envelope = envelope or Envelope()
    mixed = np.zeros(frames)
    for note in notes:
        mixed += oscillator(waveform, midi_to_hz(note), frames, sample_rate)
    mixed /= max(1, len(notes))
    return apply_envelope(mixed, envelope, sample_rate)


def render_sequence(
    steps: list[tuple[list[int], float]],
    waveform: str = DEFAULT_WAVEFORM,
    gap: float = 0.02,
    sample_rate: int = SAMPLE_RATE,
) -> np.ndarray:
    """Render ``[(notes, seconds), ...]`` back to back.

    A small gap keeps consecutive notes of the same pitch from merging into
    one long tone, which is what makes an arpeggio unreadable by ear.
    """
    chunks = []
    for notes, duration in steps:
        chunks.append(render_notes(notes, max(0.0, duration - gap),
                                   waveform, sample_rate=sample_rate))
        if gap > 0:
            chunks.append(np.zeros(int(gap * sample_rate)))
    if not chunks:
        return np.zeros(0)
    return np.concatenate(chunks)


def normalise(signal: np.ndarray, peak: float = HEADROOM) -> np.ndarray:
    if signal.size == 0:
        return signal
    loudest = float(np.abs(signal).max())
    if loudest <= 0:
        return signal
    return signal / loudest * peak


def to_wav(signal: np.ndarray, sample_rate: int = SAMPLE_RATE) -> bytes:
    """16-bit mono WAV. Standard library only."""
    pcm = (np.clip(normalise(signal), -1.0, 1.0) * 32767).astype(np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())
    return buffer.getvalue()


def silk_available() -> bool:
    try:
        from graiax import silkcoder  # noqa: F401
    except Exception:
        return False
    return True


def to_voice(signal: np.ndarray,
             sample_rate: int = SAMPLE_RATE) -> tuple[bytes, str]:
    """Best available voice encoding. Returns ``(data, format_name)``.

    Falls back to WAV rather than failing: the docs accept both, and a plugin
    that refuses to make a sound because an optional dependency is missing
    would be worse than one that sends a larger file.
    """
    audio = to_wav(signal, sample_rate)
    try:
        from graiax import silkcoder

        return silkcoder.encode(audio, audio_format="wav"), "silk"
    except Exception:
        return audio, "wav"


# --- percussion -------------------------------------------------------------
#
# Drums are the fourth classic chiptune voice: filtered noise plus a pitch
# sweep. Kept here rather than in the note path because a drum has no pitch,
# so it cannot be expressed as a MIDI number.

def render_drum(voice: int, duration: float,
                sample_rate: int = SAMPLE_RATE) -> "np.ndarray":
    """Render one drum hit. ``voice`` is a negative id from ``sequence``."""
    frames = int(duration * sample_rate)
    if frames <= 0:
        return np.zeros(0)

    if voice == -1:      # kick: a low sine swept downward
        t = np.arange(frames) / sample_rate
        sweep = np.array([110.0 * (2.718 ** (-28.0 * float(x))) + 45.0 for x in t])
        phase = np.array([0.0] * frames)
        running = 0.0
        for index in range(frames):
            running += 2 * np.pi * float(sweep[index]) / sample_rate
            phase[index] = running
        body = np.sin(phase)
        decay = np.array([2.718 ** (-9.0 * float(x)) for x in t])
        return body * decay

    if voice == -2:      # snare: noise plus a short tonal body
        t = np.arange(frames) / sample_rate
        tone = oscillator("triangle", 190.0, frames, sample_rate)
        mixed = noise(frames, seed=2) * 0.8 + tone * 0.35
        decay = np.array([2.718 ** (-16.0 * float(x)) for x in t])
        return mixed * decay

    # hi-hats: bright noise, closed decays fast and open rings on
    t = np.arange(frames) / sample_rate
    rate = 45.0 if voice == -3 else 7.0
    bright = noise(frames, seed=3)
    # Crude high-pass: differencing removes the low end and leaves the hiss.
    hissed = ndarray_diff(bright)
    decay = np.array([2.718 ** (-rate * float(x)) for x in t])
    return hissed * decay * 0.7


def ndarray_diff(signal):
    """First difference, used as a cheap high-pass for hi-hats."""
    if len(signal) < 2:
        return signal
    shifted = [0.0, *list(signal)[:-1]]
    return signal - np.array(shifted)


def render_score_steps(steps, waveform: str = DEFAULT_WAVEFORM,
                       gap: float = 0.01,
                       sample_rate: int = SAMPLE_RATE) -> "np.ndarray":
    """Render ``[(notes, seconds), ...]`` where negative notes are drums."""
    chunks = []
    for notes, duration in steps:
        span = max(0.0, duration - gap)
        if not notes:
            chunks.append(np.zeros(int(duration * sample_rate)))
            continue
        if all(note < 0 for note in notes):
            hit = render_drum(notes[0], span, sample_rate)
            chunks.append(hit)
        else:
            pitched = [note for note in notes if note >= 0]
            chunks.append(render_notes(pitched, span, waveform,
                                       sample_rate=sample_rate))
        if gap > 0:
            chunks.append(np.zeros(int(gap * sample_rate)))
    if not chunks:
        return np.zeros(0)
    return np.concatenate(chunks)
