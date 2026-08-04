"""Score parsing: a text sequence of notes, rests and bars.

Grammar
-------
Written to be typed **or** assembled by tapping blue text in a card, so every
token is short and none of them need a leading slash::

    4C          quarter note, C in octave 4 -- octave FIRST
    C4          also accepted (letter-first), but see the note below
    C4/8        eighth note      -- the digit after "/" is the denominator
    C4/16       sixteenth
    C4/2        half
    C4/1        whole
    C4.         dotted: 1.5x the written value
    C4/8.       dotted eighth
    C4/3        triplet member: three of them fill one quarter-note beat
    -           rest, same duration rules: -/8 is an eighth rest
    |           bar line (checked, never sounded)
    Cmaj E4     chords and single notes may be mixed freely

Why the octave goes first
-------------------------
``G7`` is both "G in octave 7" and "G dominant seventh", and letter-first
spelling cannot tell them apart -- any precedence rule silently plays the
wrong thing for half the users. A chord quality can never precede its root,
so writing the octave in front (``7G``) removes the ambiguity by
construction. Letter-first is still accepted for chords (``Cmaj``, ``Am``)
and for notes where nothing collides.

Duration is expressed as a fraction of a whole note, kept exact with
``Fraction`` so a bar of triplets sums to precisely one bar instead of
drifting by a sample every measure.

Pure logic: no AstrBot, no numpy, no audio.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from .theory import Chord, ParseError, parse_chord, parse_notes

#: A quarter note when nothing is written.
DEFAULT_DENOMINATOR = 4
#: Denominators we accept. 3 is the triplet marker rather than a real
#: "third note", which does not exist in standard notation.
STRAIGHT_DENOMINATORS = (1, 2, 4, 8, 16, 32)
TRIPLET_DENOMINATOR = 3

#: Drum voices. Rendered as noise bursts rather than pitches, so they carry a
#: MIDI-like id only to keep Step.notes one uniform type.
DRUM_KICK, DRUM_SNARE, DRUM_HIHAT, DRUM_OPENHAT = -1, -2, -3, -4
DRUMS = {
    "K": DRUM_KICK, "S": DRUM_SNARE, "H": DRUM_HIHAT, "O": DRUM_OPENHAT,
}
DRUM_LABELS = {
    DRUM_KICK: "底鼓", DRUM_SNARE: "军鼓",
    DRUM_HIHAT: "闭镲", DRUM_OPENHAT: "开镲",
}

REST_TOKENS = ("-", "_", "0")
BAR_TOKENS = ("|", "｜")

#: Beats per bar. 4/4 is what "默认 4 小节" assumes.
BEATS_PER_BAR = 4
DEFAULT_BARS = 4


@dataclass(frozen=True, slots=True)
class Step:
    """One sounding event: notes (empty = rest) and a length in whole notes."""

    notes: tuple[int, ...]
    length: Fraction
    #: Original text, so an error or a summary can quote what was written.
    source: str = ""

    @property
    def is_rest(self) -> bool:
        return not self.notes

    @property
    def is_drum(self) -> bool:
        return bool(self.notes) and all(note < 0 for note in self.notes)

    def seconds(self, bpm: float) -> float:
        """Convert to seconds. A quarter note lasts 60/bpm at any tempo."""
        return float(self.length) * 4.0 * (60.0 / bpm)


@dataclass(slots=True)
class Score:
    steps: list[Step] = field(default_factory=list)
    #: Bar lines the writer put in, as indexes into ``steps``.
    bar_marks: list[int] = field(default_factory=list)

    @property
    def length(self) -> Fraction:
        return sum((step.length for step in self.steps), Fraction(0))

    def seconds(self, bpm: float) -> float:
        return sum(step.seconds(bpm) for step in self.steps)

    @property
    def bars(self) -> Fraction:
        """Length measured in 4/4 bars."""
        return self.length

    def describe(self, bpm: float) -> str:
        sounded = sum(1 for step in self.steps if not step.is_rest)
        return (f"{sounded} 个音 · {float(self.bars):.2f} 小节 · "
                f"{self.seconds(bpm):.1f} 秒 · BPM {bpm:g}")


def _parse_duration(suffix: str, token: str) -> Fraction:
    """Turn the ``/8.`` part of a token into a length in whole notes."""
    dotted = suffix.endswith(".")
    if dotted:
        suffix = suffix[:-1]

    if not suffix:
        denominator = DEFAULT_DENOMINATOR
    else:
        if not suffix.startswith("/"):
            raise ParseError(f"时值要写成 /4 /8 这种：{token}")
        digits = suffix[1:]
        if not digits.isdigit():
            raise ParseError(f"时值必须是数字：{token}")
        denominator = int(digits)

    if denominator == TRIPLET_DENOMINATOR:
        # A triplet splits one beat into three, so each member is 1/3 of a
        # quarter note -- not 1/3 of a whole note, which is not a duration
        # that exists.
        length = Fraction(1, DEFAULT_DENOMINATOR) / 3
    elif denominator in STRAIGHT_DENOMINATORS:
        length = Fraction(1, denominator)
    else:
        allowed = "/".join(str(d) for d in STRAIGHT_DENOMINATORS)
        raise ParseError(f"不支持的时值 /{denominator}（可用 {allowed} 或 /3 三连音）")

    return length * Fraction(3, 2) if dotted else length


def _split_duration(token: str) -> tuple[str, str]:
    """Separate the pitch part from its trailing duration suffix."""
    for index, char in enumerate(token):
        if char == "/" or (char == "." and index):
            return token[:index], token[index:]
    return token, ""


def parse_token(token: str) -> Step | None:
    """Parse one token. Returns None for a bar line."""
    text = token.strip()
    if not text:
        return None
    if text in BAR_TOKENS:
        return None

    head, suffix = _split_duration(text)
    length = _parse_duration(suffix, text)

    if head in REST_TOKENS:
        return Step((), length, text)

    drum = DRUMS.get(head.upper())
    if drum is not None:
        return Step((drum,), length, text)

    # "C4" must be the single note C4, not a C major triad rooted there.
    # Reading it as a chord made every entry on the single-note page sound
    # three notes at once -- correct for a chord chart, wrong for a melody,
    # and silent about which it chose. A bare pitch is therefore always a
    # note; a chord needs an explicit quality ("Cmaj", "Am", "G7").
    notes = _read_pitch(head, text)
    return Step(notes, length, text)


def _read_pitch(head: str, token: str) -> tuple[int, ...]:
    """One token's pitches: a single note unless a chord quality is written.

    Note wins over chord for a bare ``letter+digit`` such as ``G7``, because
    the single-note page emits exactly that shape and a melody turning into
    triads would be both wrong and silent about it. Chords therefore need a
    spelled quality -- ``Gdom7`` or ``G4dom7`` rather than ``G7``.
    """
    try:
        return tuple(parse_notes(head))
    except ParseError:
        pass
    try:
        chord: Chord = parse_chord(head)
    except ParseError:
        raise ParseError(
            f"不认识的音符或和弦：{token}"
            "（单音写 4C / 7G，和弦写 Cmaj / Am / Gdom7）"
        ) from None
    return chord.notes


def parse_score(text: str) -> Score:
    """Parse a whole sequence. Raises ParseError naming the bad token."""
    raw = str(text or "").replace("，", " ").replace(",", " ")
    tokens = [t for t in raw.split() if t]
    if not tokens:
        raise ParseError("没有音符")

    score = Score()
    for token in tokens:
        if token in BAR_TOKENS:
            score.bar_marks.append(len(score.steps))
            continue
        step = parse_token(token)
        if step is not None:
            score.steps.append(step)
    if not score.steps:
        raise ParseError("没有音符")
    return score


def check_bars(score: Score) -> list[str]:
    """Warn where a written bar does not hold a whole number of beats.

    Returned as advice rather than an error: an incomplete final bar is
    ordinary (a pickup, or a phrase still being written), and refusing to play
    it would make the tool useless while composing.
    """
    if not score.bar_marks:
        return []
    warnings: list[str] = []
    boundaries = [0, *score.bar_marks, len(score.steps)]
    for index in range(len(boundaries) - 1):
        start, end = boundaries[index], boundaries[index + 1]
        if start >= end:
            continue
        span = sum((step.length for step in score.steps[start:end]), Fraction(0))
        if span != 1 and index < len(boundaries) - 2:
            warnings.append(
                f"第 {index + 1} 小节是 {float(span) * BEATS_PER_BAR:g} 拍，"
                f"不是 {BEATS_PER_BAR} 拍"
            )
    return warnings


def to_render_steps(score: Score, bpm: float) -> list[tuple[list[int], float]]:
    """Flatten to what ``synth.render_sequence`` consumes."""
    return [(list(step.notes), step.seconds(bpm)) for step in score.steps]


#: Ready-made one-bar drum loops, written in the same grammar players type.
#: Kept here rather than in the card so they can be parsed and tested.
DRUM_PATTERNS = {
    "basic": ("基本节奏", "K H/8 H/8 S H/8 H/8 K H/8 H/8 S H/8 H/8"),
    "rock":  ("摇滚", "K H/8 K/8 S H/8 H/8 K H/8 K/8 S H/8 H/8"),
    "disco": ("迪斯科", "K O/8 H/8 S O/8 H/8 K O/8 H/8 S O/8 H/8"),
}
