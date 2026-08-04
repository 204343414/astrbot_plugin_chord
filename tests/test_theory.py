"""Note and chord theory.

Every interval table here is checked against a chord whose notes are common
knowledge (C major is C E G; G7 is G B D F). A transposed table would still
produce valid-looking output and only be caught by ear, so the assertions name
actual notes rather than restating the constant under test.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chord import theory as th  # noqa: E402


def names(chord) -> list[str]:
    return [th.SHARP_NAMES[n % 12] for n in chord.notes]


# --- pitch ------------------------------------------------------------------

def test_middle_c_is_midi_60_and_a4_is_440hz():
    assert th.note_to_midi("C4") == 60
    assert th.note_to_midi("A4") == 69
    assert th.midi_to_hz(69) == pytest.approx(440.0)
    assert th.midi_to_hz(60) == pytest.approx(261.626, rel=1e-4)


def test_a_bare_note_name_defaults_to_the_middle_octave():
    assert th.note_to_midi("C") == th.note_to_midi("C4")


def test_an_octave_up_doubles_the_frequency():
    assert th.midi_to_hz(72) == pytest.approx(2 * th.midi_to_hz(60))


@pytest.mark.parametrize("sharp,flat", [
    ("C#", "Db"), ("D#", "Eb"), ("F#", "Gb"), ("G#", "Ab"), ("A#", "Bb"),
])
def test_sharps_and_flats_name_the_same_pitch(sharp, flat):
    assert th.note_to_midi(sharp + "4") == th.note_to_midi(flat + "4")


def test_unicode_accidentals_are_accepted():
    assert th.note_to_midi("C♯4") == th.note_to_midi("C#4")
    assert th.note_to_midi("B♭4") == th.note_to_midi("Bb4")


def test_solfa_digits_map_to_the_major_scale():
    """1=do=C, so a group member who only reads 简谱 can still play."""
    assert th.note_to_midi("1") == th.note_to_midi("C")
    assert th.note_to_midi("5") == th.note_to_midi("G")


@pytest.mark.parametrize("bad", ["", "H", "Cx", "音"])
def test_nonsense_is_refused_with_a_reason(bad):
    with pytest.raises(th.ParseError):
        th.note_to_midi(bad)


def test_double_accidentals_are_real_notation_but_mixing_them_is_not():
    """C## is D -- valid. C#b is always a typo, so it must not silently pass."""
    assert th.note_to_midi("C##4") == th.note_to_midi("D4")
    assert th.note_to_midi("Dbb4") == th.note_to_midi("C4")
    for typo in ("C#b", "Cb#4", "C##b"):
        with pytest.raises(th.ParseError):
            th.note_to_midi(typo)


def test_out_of_range_octaves_are_refused():
    with pytest.raises(th.ParseError):
        th.note_to_midi("C99")


# --- chord spelling ---------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("C",     ["C", "E", "G"]),
    ("Cmaj",  ["C", "E", "G"]),
    ("Cm",    ["C", "D#", "G"]),
    ("Am",    ["A", "C", "E"]),
    ("G7",    ["G", "B", "D", "F"]),
    ("Cmaj7", ["C", "E", "G", "B"]),
    ("Am7",   ["A", "C", "E", "G"]),
    ("Cdim",  ["C", "D#", "F#"]),
    ("Caug",  ["C", "E", "G#"]),
    ("Csus4", ["C", "F", "G"]),
    ("Csus2", ["C", "D", "G"]),
    ("F#m7",  ["F#", "A", "C#", "E"]),
])
def test_chords_spell_the_notes_everyone_knows(text, expected):
    assert names(th.parse_chord(text)) == expected


def test_uppercase_M_is_major_and_lowercase_m_is_minor():
    """The one case fold that must never happen.

    Lowercasing the alias table made "CM" a C minor at import time, and the
    duplicate-alias guard is what caught it.
    """
    assert names(th.parse_chord("CM")) == ["C", "E", "G"]
    assert names(th.parse_chord("Cm")) == ["C", "D#", "G"]


def test_a_trailing_seven_is_a_chord_quality_not_an_octave():
    """Regression: G7 parsed as "G in octave 7" and played four octaves high.

    It raised nothing -- the chord was simply wrong -- which is why the
    assertion checks the actual MIDI root rather than just the quality.
    """
    chord = th.parse_chord("G7")
    assert chord.root == th.note_to_midi("G4")
    assert names(chord) == ["G", "B", "D", "F"]


def test_an_explicit_octave_still_works_with_a_quality():
    assert th.parse_chord("C5m").root == th.note_to_midi("C5")
    assert names(th.parse_chord("C5m")) == ["C", "D#", "G"]


def test_a_bare_note_is_a_major_triad_like_a_chord_chart():
    assert th.parse_chord("F").quality.key == "maj"


def test_case_is_forgiving_everywhere_except_m():
    assert th.parse_chord("CMAJ7").quality.key == "maj7"
    assert th.parse_chord("cSuS4").quality.key == "sus4"


@pytest.mark.parametrize("bad", ["", "Cwat", "Xmaj", "C#zz"])
def test_unknown_chords_are_refused(bad):
    with pytest.raises(th.ParseError):
        th.parse_chord(bad)


# --- quality table ----------------------------------------------------------

def test_every_quality_starts_on_the_root():
    for quality in th.QUALITIES:
        assert quality.intervals[0] == 0, quality.key


def test_intervals_are_strictly_ascending():
    """A descending pair would mean a typo, and would sound merely 'odd'."""
    for quality in th.QUALITIES:
        assert list(quality.intervals) == sorted(set(quality.intervals)), quality.key


def test_every_quality_has_a_chinese_label():
    for quality in th.QUALITIES:
        assert quality.label and not quality.label.isascii(), quality.key


def test_aliases_are_unique_across_qualities():
    seen: dict[str, str] = {}
    for quality in th.QUALITIES:
        for alias in (quality.key, *quality.aliases):
            assert seen.setdefault(alias, quality.key) == quality.key, alias


def test_major_and_minor_differ_only_in_the_third():
    major = th.QUALITY_BY_KEY["maj"].intervals
    minor = th.QUALITY_BY_KEY["min"].intervals
    assert major[0] == minor[0] and major[2] == minor[2]
    assert major[1] - minor[1] == 1, "大三度比小三度高一个半音"


# --- inversions and arpeggios -----------------------------------------------

def test_an_inversion_keeps_the_same_pitch_classes():
    root_position = th.build_chord("C", "maj")
    first = th.build_chord("C", "maj", inversion=1)
    assert sorted(n % 12 for n in first.notes) == \
        sorted(n % 12 for n in root_position.notes)
    assert first.notes != root_position.notes


def test_an_inversion_raises_the_lowest_note_by_an_octave():
    first = th.build_chord("C", "maj", inversion=1)
    assert th.note_to_midi("C5") in first.notes


@pytest.mark.parametrize("pattern", [p for p in th.ARPEGGIOS if p != "block"])
def test_arpeggios_only_use_notes_from_the_chord(pattern):
    chord = th.build_chord("C", "maj7")
    order = th.arpeggio_order(chord, pattern)
    assert order, pattern
    assert set(order) <= set(chord.notes)


def test_block_chords_have_no_arpeggio_order():
    assert th.arpeggio_order(th.build_chord("C"), "block") == []


def test_an_unknown_arpeggio_is_refused():
    with pytest.raises(th.ParseError):
        th.arpeggio_order(th.build_chord("C"), "spiral")


# --- note lists -------------------------------------------------------------

def test_note_lists_parse_with_or_without_octaves():
    assert th.parse_notes("C4 E4 G4") == [60, 64, 67]
    assert th.parse_notes("C, E, G") == [60, 64, 67]


def test_an_empty_note_list_is_refused():
    with pytest.raises(th.ParseError):
        th.parse_notes("   ")


def test_describe_never_leaks_raw_midi_numbers():
    text = th.parse_chord("Am7").describe()
    assert "Amin7" in text and "A4" in text
    assert "57" not in text
