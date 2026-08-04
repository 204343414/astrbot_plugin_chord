"""Note and chord theory. Pure data -- no AstrBot, no numpy, no audio.

Notation
--------
Scientific pitch notation, which is what makes one grammar cover both cases:

    C4        a single note, middle C
    C         the same note with the octave left out (defaults to OCTAVE)
    C#5 / Db5 a sharp or flat, either spelling
    Cmaj      a chord -- letters after the note name are a chord suffix
    Am7       root A, quality m7

A digit after the letter is always an octave; anything else is always a chord
quality, so the two can never be confused by the parser.

Everything here is deliberately testable on its own: a wrong interval table
would be inaudible in review but obvious in a test.
"""
from __future__ import annotations

import re as _re
from dataclasses import dataclass

#: Semitone names, sharp spelling. Index == pitch class.
SHARP_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
#: Flat spelling of the same pitch classes, for display.
FLAT_NAMES = ("C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B")

#: Natural notes and their pitch class. Everything else is derived.
NATURALS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

#: Default octave when the user writes a bare note name. 4 is the octave that
#: contains middle C, which is where a keyboard's C major sits.
OCTAVE = 4

#: MIDI note 69 is A4 = 440 Hz; that anchors every frequency.
A4_MIDI = 69
A4_HZ = 440.0

#: Simplified pinyin/Chinese aliases, so 群友 can type what they know.
SOLFA = {"1": "C", "2": "D", "3": "E", "4": "F", "5": "G", "6": "A", "7": "B"}


@dataclass(frozen=True, slots=True)
class Quality:
    """One chord quality: its canonical name, intervals and Chinese label."""

    key: str
    label: str
    #: Semitones above the root.
    intervals: tuple[int, ...]
    aliases: tuple[str, ...] = ()


#: The qualities the buttons offer. Ordered by how often they actually appear
#: in songs, because that ordering is what the keyboard layout follows.
QUALITIES: tuple[Quality, ...] = (
    Quality("maj", "大三和弦", (0, 4, 7), ("", "M", "major")),
    Quality("min", "小三和弦", (0, 3, 7), ("m", "-", "minor")),
    Quality("7", "属七和弦", (0, 4, 7, 10), ("dom7",)),
    Quality("maj7", "大七和弦", (0, 4, 7, 11), ("M7", "Δ")),
    Quality("min7", "小七和弦", (0, 3, 7, 10), ("m7", "-7")),
    Quality("dim", "减三和弦", (0, 3, 6), ("o",)),
    Quality("aug", "增三和弦", (0, 4, 8), ("+",)),
    Quality("sus2", "挂二和弦", (0, 2, 7), ()),
    Quality("sus4", "挂四和弦", (0, 5, 7), ()),
    Quality("add9", "加九和弦", (0, 4, 7, 14), ()),
    Quality("6", "大六和弦", (0, 4, 7, 9), ("maj6",)),
    Quality("m6", "小六和弦", (0, 3, 7, 9), ("min6",)),
)

QUALITY_BY_KEY = {q.key: q for q in QUALITIES}

#: Every accepted spelling -> canonical key. Built once so parsing is a lookup
#: rather than a scan, and so a duplicate alias fails loudly at import time.
#:
#: Case is **significant** and must not be folded: in chord notation "M" means
#: major and "m" means minor, so lowercasing the table would silently make
#: every "CM" a C minor. Lookup therefore tries the exact spelling first and
#: only then a lowercased one, so "MAJ7" still works while "m" stays minor.
_ALIAS_TO_KEY: dict[str, str] = {}
for _q in QUALITIES:
    for _name in (_q.key, *_q.aliases):
        if _name in _ALIAS_TO_KEY and _ALIAS_TO_KEY[_name] != _q.key:
            raise RuntimeError(f"和弦别名冲突: {_name!r}")
        _ALIAS_TO_KEY[_name] = _q.key


def _lookup_quality(text: str) -> str | None:
    """Case-sensitive first, then a forgiving fallback.

    "M" vs "m" is the one distinction that must survive; everything else
    (MAJ7, Sus4, DIM) is safe to normalise.
    """
    if text in _ALIAS_TO_KEY:
        return _ALIAS_TO_KEY[text]
    if text in ("M", "m"):
        return None                      # already checked; do not fold these
    lowered = text.lower()
    for name, key in _ALIAS_TO_KEY.items():
        if name.lower() == lowered and name not in ("M", "m"):
            return key
    return None


class ParseError(ValueError):
    """Raised with a human-readable reason, which is shown to the player."""


def midi_to_hz(midi: float) -> float:
    return A4_HZ * (2.0 ** ((midi - A4_MIDI) / 12.0))


def signed_offset(name: str) -> int:
    """Semitones from C, **without** wrapping into 0..11.

    Cb is one semitone below C, which is the B *of the previous octave* -- so
    it must come out as -1, not 11. Wrapping first and then adding the octave
    put Cb4 on B4 instead of B3, and B#4 on C4 instead of C5: a semitone
    right, an octave wrong, and silent about it.
    """
    text = name.strip().replace("♯", "#").replace("♭", "b")
    if not text:
        raise ParseError("音名为空")
    letter = text[0].upper()
    if letter in SOLFA:
        letter = SOLFA[letter]
    if letter not in NATURALS:
        raise ParseError(f"不认识的音名：{name}")
    value = NATURALS[letter]
    accidentals = text[1:]
    if "#" in accidentals and ("b" in accidentals or "B" in accidentals):
        raise ParseError(f"升号和降号不能混用：{name}")
    for accidental in accidentals:
        if accidental == "#":
            value += 1
        elif accidental in ("b", "B"):
            value -= 1
        else:
            raise ParseError(f"不认识的升降号：{accidental}")
    return value


def pitch_class(name: str) -> int:
    """'C#' / 'Db' -> 1. Raises ParseError on anything else."""
    text = name.strip().replace("♯", "#").replace("♭", "b")
    if not text:
        raise ParseError("音名为空")
    letter = text[0].upper()
    if letter in SOLFA:
        letter = SOLFA[letter]
    if letter not in NATURALS:
        raise ParseError(f"不认识的音名：{name}")
    value = NATURALS[letter]
    accidentals = text[1:]
    # Double sharps and double flats are real notation (C## is D), but mixing
    # the two in one name is not -- it is always a typo, and silently
    # cancelling them out would play a note the writer never asked for.
    if "#" in accidentals and ("b" in accidentals or "B" in accidentals):
        raise ParseError(f"升号和降号不能混用：{name}")
    for accidental in accidentals:
        if accidental == "#":
            value += 1
        elif accidental in ("b", "B"):
            value -= 1
        else:
            raise ParseError(f"不认识的升降号：{accidental}")
    return value % 12


#: Octave-first spelling: 4C, 7G, 4C#, 4Bb.
#:
#: This exists because letter-first collides with chord names: "G7" is both
#: "G in octave 7" and "G dominant seventh", and no rule can settle that
#: without silently guessing wrong for someone. A chord quality can never
#: precede its root, so putting the octave in front removes the ambiguity by
#: construction rather than by precedence.
#: Also accepts a *leading* accidental (``#4C``), which is what the card's
#: ♯/♭ buttons produce: they are tapped before the note, so the text lands in
#: front of it. Rejecting that shape would make the two buttons unusable.
_OCTAVE_FIRST_RE = _re.compile(r"^([#b]?)([0-9])([A-Ga-g])([#b]?)$")


def note_to_midi(text: str, default_octave: int = OCTAVE) -> int:
    """'C4' -> 60, '4C' -> 60, 'C' -> 60, 'A#3' -> 58."""
    raw = str(text or "").strip().replace("♯", "#").replace("♭", "b")
    if not raw:
        raise ParseError("音名为空")

    prefixed = _OCTAVE_FIRST_RE.match(raw)
    if prefixed:
        leading, octave_text, letter, trailing = prefixed.groups()
        if leading and trailing:
            raise ParseError(f"升降号只能写一个：{text}")
        return _midi_from(letter + (leading or trailing), int(octave_text))

    digits = ""
    while raw and (raw[-1].isdigit() or (raw[-1] == "-" and digits)):
        digits = raw[-1] + digits
        raw = raw[:-1]
    # A leading solfa digit ("1" = C) is a note, not an octave.
    if not raw and digits:
        raw, digits = digits[0], digits[1:]

    return _midi_from(raw, int(digits) if digits else default_octave)


def _midi_from(name: str, octave: int) -> int:
    if not -1 <= octave <= 9:
        raise ParseError(f"八度超出范围：{octave}（应在 -1~9）")
    # signed_offset, not pitch_class: an accidental that crosses the C
    # boundary must take the octave with it (Cb4 is B3, B#4 is C5).
    midi = (octave + 1) * 12 + signed_offset(name)
    if not 0 <= midi <= 127:
        raise ParseError(f"音高超出范围：{name}{octave}")
    return midi


def midi_to_name(midi: int, flats: bool = False) -> str:
    names = FLAT_NAMES if flats else SHARP_NAMES
    return f"{names[midi % 12]}{midi // 12 - 1}"


def parse_quality(text: str) -> Quality:
    key = _lookup_quality(str(text or "").strip())
    if key is None:
        raise ParseError(f"不认识的和弦类型：{text}")
    return QUALITY_BY_KEY[key]


@dataclass(frozen=True, slots=True)
class Chord:
    root: int                 # MIDI note of the root
    quality: Quality
    inversion: int = 0

    @property
    def notes(self) -> tuple[int, ...]:
        """MIDI notes, with any inversion applied.

        An inversion lifts the lowest notes an octave rather than reordering
        the list, which is what actually happens on an instrument.
        """
        base = [self.root + step for step in self.quality.intervals]
        for index in range(self.inversion % len(base)):
            base[index] += 12
        return tuple(sorted(base))

    @property
    def name(self) -> str:
        root = SHARP_NAMES[self.root % 12]
        suffix = "" if self.quality.key == "maj" else self.quality.key
        return f"{root}{suffix}"

    @property
    def note_names(self) -> tuple[str, ...]:
        return tuple(midi_to_name(note) for note in self.notes)

    def describe(self) -> str:
        return f"{self.name}（{self.quality.label}）: {' '.join(self.note_names)}"


def build_chord(root: str, quality: str = "maj", inversion: int = 0) -> Chord:
    return Chord(note_to_midi(root), parse_quality(quality), inversion)


def parse_chord(text: str) -> Chord:
    """Parse 'Cmaj7' / 'Am' / 'F#m7' / 'C' into a Chord.

    A bare note name is a major triad, matching how chord charts are written.
    """
    raw = str(text or "").strip().replace("♯", "#").replace("♭", "b")
    if not raw:
        raise ParseError("和弦为空")

    # Root = leading letter + accidentals; then an optional octave; the rest
    # is the chord quality.
    cursor = 1
    while cursor < len(raw) and raw[cursor] in "#b":
        cursor += 1
    letter_end = cursor

    octave = ""
    while cursor < len(raw) and raw[cursor].isdigit():
        octave += raw[cursor]
        cursor += 1
    remainder = raw[cursor:]

    # "G7" is a dominant seventh, not G in octave 7. A trailing digit run with
    # nothing after it belongs to the quality whenever it spells one. Getting
    # this wrong did not raise -- it silently played G7 four octaves too high,
    # which is exactly the kind of bug an ear catches and a type checker never
    # would.
    if octave and not remainder and _lookup_quality(octave) is not None:
        remainder, octave = octave, ""

    quality = parse_quality(remainder or "maj")
    return Chord(note_to_midi(raw[:letter_end] + octave), quality)


def parse_notes(text: str) -> list[int]:
    """Parse 'C4 E4 G4' or 'C E G' into MIDI notes."""
    parts = [p for p in str(text or "").replace(",", " ").split() if p]
    if not parts:
        raise ParseError("没有音符")
    return [note_to_midi(part) for part in parts]


#: Arpeggio patterns, as indexes into the chord's notes. Negative wraps.
ARPEGGIOS: dict[str, tuple[str, tuple[int, ...]]] = {
    "block": ("柱式（同时）", ()),
    "up": ("上行", (0, 1, 2, 3)),
    "down": ("下行", (3, 2, 1, 0)),
    "updown": ("上下行", (0, 1, 2, 3, 2, 1)),
    "alberti": ("阿尔贝蒂低音", (0, 2, 1, 2)),
}


def arpeggio_order(chord: Chord, pattern: str) -> list[int]:
    """MIDI notes in playing order for ``pattern``. Empty means play together."""
    label_and_steps = ARPEGGIOS.get(pattern)
    if label_and_steps is None:
        raise ParseError(f"不认识的分解型：{pattern}")
    _, steps = label_and_steps
    notes = chord.notes
    if not steps:
        return []
    return [notes[step % len(notes)] for step in steps]
