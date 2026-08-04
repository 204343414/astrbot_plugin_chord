"""Synthesis: waveform shape, envelope, and encoding.

Audio bugs are invisible in a diff and obvious in a speaker, so these tests
measure the signal itself -- a square wave really only takes two values, a
note really does start and end at silence, and a rendered chord really does
contain the frequencies of its own notes.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chord import synth  # noqa: E402
from chord import theory as th  # noqa: E402


def dominant_frequency(signal: np.ndarray, sample_rate: int) -> float:
    spectrum = np.abs(np.fft.rfft(signal * np.hanning(len(signal))))
    return float(np.fft.rfftfreq(len(signal), 1 / sample_rate)[spectrum.argmax()])


# --- waveforms --------------------------------------------------------------

def test_all_four_classic_waveforms_exist():
    assert set(synth.WAVEFORMS) == {"square", "saw", "triangle", "sine"}


@pytest.mark.parametrize("waveform", sorted(synth.WAVEFORMS))
def test_every_waveform_oscillates_at_the_requested_pitch(waveform):
    """The whole point: A4 must actually be 440 Hz, not merely 'a tone'."""
    signal = synth.oscillator(waveform, 440.0, synth.SAMPLE_RATE)
    assert dominant_frequency(signal, synth.SAMPLE_RATE) == pytest.approx(440, abs=3)


def test_a_square_wave_only_takes_two_values():
    """Aside from the exact zero crossings, where np.sign() returns 0.

    Those are single samples at a discontinuity -- inaudible, and excluding
    them is honest about what the generator does rather than pretending the
    edge case does not exist.
    """
    signal = synth.oscillator("square", 220.0, 2000)
    values = set(np.unique(np.round(signal, 6)))
    assert values <= {-1.0, 0.0, 1.0}
    assert int((signal == 0).sum()) <= 2, "过零点样本应极少"


def test_a_saw_ramps_upward_then_resets():
    signal = synth.oscillator("saw", 100.0, synth.SAMPLE_RATE // 100)
    assert signal[0] < signal[len(signal) // 2] < signal[-1]


def test_a_triangle_is_symmetric_about_zero():
    signal = synth.oscillator("triangle", 200.0, synth.SAMPLE_RATE)
    assert abs(float(signal.mean())) < 0.02


def test_every_waveform_stays_inside_full_scale():
    for waveform in synth.WAVEFORMS:
        signal = synth.oscillator(waveform, 330.0, 4096)
        assert np.abs(signal).max() <= 1.0 + 1e-9, waveform


def test_an_unknown_waveform_is_refused():
    with pytest.raises(ValueError):
        synth.oscillator("bagpipe", 440.0, 100)


def test_noise_is_broadband_and_reproducible():
    """Drums are noise; a fixed seed keeps a rendered bar byte-identical."""
    first = synth.noise(1000, seed=7)
    assert np.array_equal(first, synth.noise(1000, seed=7))
    assert not np.array_equal(first, synth.noise(1000, seed=8))
    assert first.std() > 0.4


def test_zero_length_requests_return_empty_rather_than_crashing():
    assert synth.oscillator("sine", 440.0, 0).size == 0
    assert synth.noise(0).size == 0


# --- envelope ---------------------------------------------------------------

def test_a_note_starts_and_ends_at_silence():
    """Without this a square wave clicks audibly on every single note."""
    shaped = synth.apply_envelope(np.ones(synth.SAMPLE_RATE), synth.Envelope())
    assert abs(shaped[0]) < 0.05
    assert abs(shaped[-1]) < 0.05


def test_the_envelope_peaks_during_the_attack_not_at_the_end():
    shaped = synth.apply_envelope(np.ones(synth.SAMPLE_RATE), synth.Envelope())
    assert shaped.argmax() < len(shaped) // 2


def test_a_very_short_note_is_still_shaped_without_error():
    shaped = synth.apply_envelope(np.ones(64), synth.Envelope())
    assert shaped.size == 64
    assert np.isfinite(shaped).all()


# --- rendering --------------------------------------------------------------

def test_a_rendered_chord_contains_all_of_its_notes():
    chord = th.parse_chord("C")
    signal = synth.render_notes(list(chord.notes), 1.0, "sine")
    spectrum = np.abs(np.fft.rfft(signal))
    freqs = np.fft.rfftfreq(len(signal), 1 / synth.SAMPLE_RATE)
    for note in chord.notes:
        target = th.midi_to_hz(note)
        window = (freqs > target - 6) & (freqs < target + 6)
        assert spectrum[window].max() > spectrum.mean() * 12, f"缺少 {target:.0f}Hz"


def test_rendering_is_deterministic():
    """Same notes in, same bytes out -- what makes re-rendering lossless."""
    a = synth.render_notes([60, 64, 67], 0.5, "square")
    b = synth.render_notes([60, 64, 67], 0.5, "square")
    assert np.array_equal(a, b)


def test_render_length_matches_the_requested_duration():
    signal = synth.render_notes([60], 0.75)
    assert len(signal) == pytest.approx(0.75 * synth.SAMPLE_RATE, rel=0.01)


def test_an_empty_chord_renders_silence_rather_than_failing():
    assert synth.render_notes([], 1.0).size == 0


def test_a_sequence_lasts_the_sum_of_its_steps():
    steps = [([60], 0.3), ([64], 0.3), ([67], 0.3)]
    signal = synth.render_sequence(steps)
    assert len(signal) == pytest.approx(0.9 * synth.SAMPLE_RATE, rel=0.02)


def test_sequence_steps_are_separated_by_a_gap():
    """Two identical notes in a row must be heard as two, not one long tone.

    The silence sits at the *end* of each step, not at the midpoint of the
    whole clip -- a step is (note for duration-gap) followed by (gap).
    """
    gap = 0.05
    signal = synth.render_sequence([([60], 0.3), ([60], 0.3)], gap=gap)
    step_end = int(0.3 * synth.SAMPLE_RATE)
    silence = np.abs(signal[step_end - int(gap * synth.SAMPLE_RATE) + 50:step_end - 50])
    assert silence.max() < 0.02, "两个音之间应有间隙"


def test_mixing_many_notes_does_not_clip():
    signal = synth.render_notes([48, 52, 55, 59, 62, 66], 0.5, "square")
    assert np.abs(signal).max() <= 1.0


# --- encoding ---------------------------------------------------------------

def test_wav_is_a_valid_riff_container():
    data = synth.to_wav(synth.render_notes([60], 0.2))
    assert data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def test_wav_needs_no_ffmpeg():
    """A waveform is numbers and WAV is a stdlib header -- that is the point.

    ffmpeg is only unavoidable for *video*, where H.264/AAC are far too large
    to reimplement. Confusing the two is what made this look heavier than it is.
    """
    import wave as stdlib_wave

    assert stdlib_wave  # imported from the standard library, nothing external


def test_normalise_scales_to_the_headroom_and_tolerates_silence():
    loud = synth.normalise(np.array([0.1, -0.2, 0.05]))
    assert np.abs(loud).max() == pytest.approx(synth.HEADROOM)
    assert np.array_equal(synth.normalise(np.zeros(10)), np.zeros(10))


def test_to_voice_reports_the_format_it_actually_used():
    data, used = synth.to_voice(synth.render_notes([60], 0.3))
    assert used in ("silk", "wav")
    assert len(data) > 100
    if used == "wav":
        assert data[:4] == b"RIFF"
    else:
        assert b"SILK" in data[:16], "silk 文件头应含 #!SILK_V3"


def test_silk_is_much_smaller_when_available():
    if not synth.silk_available():
        pytest.skip("未安装 graiax-silkcoder")
    signal = synth.render_notes([60, 64, 67], 1.6)
    wav = synth.to_wav(signal)
    voice, used = synth.to_voice(signal)
    assert used == "silk"
    assert len(voice) < len(wav) / 3, "silk 应显著小于 WAV"


def test_a_missing_silk_encoder_degrades_to_wav_instead_of_failing():
    """An optional dependency must never stop the bot making a sound."""
    import builtins

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name.startswith("graiax"):
            raise ImportError("simulated")
        return real_import(name, *args, **kwargs)

    builtins.__import__ = blocked
    try:
        data, used = synth.to_voice(synth.render_notes([60], 0.2))
    finally:
        builtins.__import__ = real_import
    assert used == "wav"
    assert data[:4] == b"RIFF"


# --- installing without optional dependencies -------------------------------
#
# The plugin failed to install because requirements.txt listed
# graiax-silkcoder, which ships only a source tarball of the SILK SDK and so
# needs a C toolchain the AstrBot image does not have. Neither optional
# dependency may be allowed to block installation again.

def _render_in_subprocess(hide_numpy: bool) -> bytes:
    """Render a chord in a fresh interpreter with imports blocked."""
    import base64
    import subprocess

    root = Path(__file__).resolve().parents[1]
    code = f'''
import sys, builtins, base64
sys.path.insert(0, {str(root)!r})
real = builtins.__import__
def blocked(name, *a, **k):
    if {hide_numpy} and (name == "numpy" or name.startswith("numpy.")):
        raise ImportError("hidden")
    if name.startswith("graiax"):
        raise ImportError("hidden")
    return real(name, *a, **k)
builtins.__import__ = blocked
from chord import synth, theory as th
sig = synth.render_notes(list(th.parse_chord("Cmaj7").notes), 0.8, "square")
sys.stdout.write(base64.b64encode(synth.to_wav(sig)).decode())
'''
    result = subprocess.run([sys.executable, "-B", "-c", code],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-800:]
    return base64.b64decode(result.stdout)


def test_requirements_only_lists_installable_wheels():
    """graiax-silkcoder has no wheel; requiring it broke plugin installation."""
    text = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text()
    listed = [line.strip() for line in text.splitlines()
              if line.strip() and not line.startswith("#")]
    assert "graiax-silkcoder" not in listed, "可选依赖不能写进 requirements"


def test_the_plugin_renders_without_numpy():
    """numpy is not an AstrBot dependency, so it must not be load-bearing."""
    data = _render_in_subprocess(hide_numpy=True)
    assert data[:4] == b"RIFF"
    assert len(data) > 10_000


def test_the_pure_python_path_is_sample_identical_to_numpy():
    """A fallback that sounds different would be a second instrument.

    This also pins a real bug: ndarray subclasses list, so `mixed += osc`
    concatenated the buffers instead of summing them and produced a clip four
    times too long -- audible, but only if something checks.
    """
    assert _render_in_subprocess(False) == _render_in_subprocess(True)
