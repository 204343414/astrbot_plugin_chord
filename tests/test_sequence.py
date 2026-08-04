"""Score grammar: durations, triplets, bars, drums.

Timing errors are the ones you cannot see in a diff and cannot quite hear
either -- a triplet that is 1/1000 short only drifts audibly after a few bars.
So durations are asserted as exact fractions rather than floats.
"""
import sys
from fractions import Fraction
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chord import sequence as sq  # noqa: E402
from chord import theory as th  # noqa: E402


def notes_of(token: str):
    step = sq.parse_token(token)
    return step.notes if step else None


# --- octave-first spelling --------------------------------------------------

def test_octave_first_and_letter_first_agree_where_unambiguous():
    assert th.note_to_midi("4C") == th.note_to_midi("C4") == 60
    assert th.note_to_midi("3A") == th.note_to_midi("A3")


def test_octave_first_removes_the_g7_ambiguity():
    """'G7' is both a pitch and a chord; '7G' can only ever be the pitch.

    This is the whole reason the grammar puts the octave first. Any
    precedence rule on the letter-first spelling silently plays the wrong
    thing for one group of users.
    """
    assert th.note_to_midi("7G") == 103
    assert notes_of("7G") == (103,)
    # Spelled quality is still a chord, and is unaffected.
    assert notes_of("Gdom7") == (67, 71, 74, 77)


def test_a_bare_pitch_is_one_note_not_a_triad():
    """On the melody page 4C must sound alone; reading it as C major made
    every tapped note play three pitches without saying so."""
    assert notes_of("4C") == (60,)
    assert notes_of("C4") == (60,)
    assert notes_of("Cmaj") == (60, 64, 67)


def test_accidentals_work_in_octave_first_spelling():
    assert notes_of("4C#") == (61,)
    assert notes_of("4Bb") == (70,)


def test_midi_range_is_enforced_at_the_top():
    """MIDI stops at 127 = G9, so A9 and B9 are not playable."""
    assert th.note_to_midi("9G") == 127
    for impossible in ("9A", "9B"):
        with pytest.raises(th.ParseError):
            th.note_to_midi(impossible)


# --- durations --------------------------------------------------------------

def test_a_bare_note_is_a_quarter():
    assert sq.parse_token("4C").length == Fraction(1, 4)


@pytest.mark.parametrize("token,expected", [
    ("4C/1", Fraction(1)), ("4C/2", Fraction(1, 2)), ("4C/4", Fraction(1, 4)),
    ("4C/8", Fraction(1, 8)), ("4C/16", Fraction(1, 16)),
    ("4C/32", Fraction(1, 32)),
])
def test_straight_durations(token, expected):
    assert sq.parse_token(token).length == expected


def test_a_dot_adds_half_again():
    assert sq.parse_token("4C.").length == Fraction(3, 8)
    assert sq.parse_token("4C/8.").length == Fraction(3, 16)


def test_a_dotted_quarter_plus_an_eighth_is_exactly_half_a_bar():
    """The classic rhythm; if this drifts, everything after it drifts too."""
    score = sq.parse_score("4C. 4D/8")
    assert score.length == Fraction(1, 2)


def test_three_triplets_fill_exactly_one_beat():
    """Not 0.333 x 3 = 0.999 -- exactly one quarter note.

    Fractions are used precisely so a bar of triplets cannot accumulate a
    rounding error that shifts every later note.
    """
    score = sq.parse_score("4C/3 4E/3 4G/3")
    assert score.length == Fraction(1, 4)


def test_a_bar_of_triplets_stays_a_bar():
    score = sq.parse_score(" ".join(["4C/3"] * 12))
    assert score.length == Fraction(1), "四拍三连音应正好一小节"


def test_an_unsupported_duration_is_refused_by_name():
    with pytest.raises(th.ParseError, match="不支持的时值"):
        sq.parse_token("4C/5")


def test_a_malformed_duration_is_refused():
    with pytest.raises(th.ParseError):
        sq.parse_token("4C/x")


# --- rests, bars ------------------------------------------------------------

def test_rests_sound_nothing_but_take_time():
    step = sq.parse_token("-")
    assert step.is_rest and step.length == Fraction(1, 4)
    assert sq.parse_token("-/8").length == Fraction(1, 8)


def test_bar_lines_are_recorded_but_never_sounded():
    score = sq.parse_score("4C 4D | 4E 4F")
    assert len(score.steps) == 4
    assert score.bar_marks == [2]


def test_an_incomplete_bar_warns_instead_of_failing():
    """A half-written bar is normal while composing; refusing it would make
    the tool unusable exactly when it is most useful."""
    score = sq.parse_score("4C 4D | 4E 4F 4G 4A")
    warnings = sq.check_bars(score)
    assert warnings and "2 拍" in warnings[0]
    assert score.steps, "仍然可以播放"


def test_a_complete_four_four_bar_raises_no_warning():
    score = sq.parse_score("4C 4D 4E 4F | 4G 4A 4B 5C")
    assert sq.check_bars(score) == []


# --- drums ------------------------------------------------------------------

@pytest.mark.parametrize("token,voice", [
    ("K", sq.DRUM_KICK), ("S", sq.DRUM_SNARE),
    ("H", sq.DRUM_HIHAT), ("O", sq.DRUM_OPENHAT),
])
def test_drum_tokens_map_to_voices(token, voice):
    step = sq.parse_token(token)
    assert step.notes == (voice,)
    assert step.is_drum


def test_drums_take_durations_like_notes():
    assert sq.parse_token("H/16").length == Fraction(1, 16)


def test_drums_and_pitches_mix_in_one_score():
    score = sq.parse_score("K 4C H/8 Cmaj S")
    kinds = [(s.is_drum, s.is_rest) for s in score.steps]
    assert kinds == [(True, False), (False, False), (True, False),
                     (False, False), (True, False)]


def test_drum_ids_never_collide_with_real_pitches():
    """Drums are negative so a renderer can tell them apart by sign alone."""
    assert all(voice < 0 for voice in sq.DRUMS.values())
    assert len(set(sq.DRUMS.values())) == len(sq.DRUMS)


# --- tempo ------------------------------------------------------------------

def test_a_quarter_note_lasts_sixty_over_bpm():
    step = sq.parse_token("4C")
    assert step.seconds(120) == pytest.approx(0.5)
    assert step.seconds(60) == pytest.approx(1.0)


def test_four_four_bars_last_what_the_tempo_says():
    score = sq.parse_score("4C 4D 4E 4F")
    assert score.seconds(120) == pytest.approx(2.0)
    assert score.seconds(60) == pytest.approx(4.0)


def test_the_summary_reports_notes_bars_and_seconds():
    score = sq.parse_score("4C 4D 4E 4F | K S K S")
    text = score.describe(120)
    assert "8 个音" in text and "2.00 小节" in text and "BPM 120" in text


# --- whole scores -----------------------------------------------------------

def test_commas_and_full_width_separators_are_accepted():
    """People type on phones; a stray Chinese comma should not be an error."""
    assert len(sq.parse_score("4C，4D, 4E").steps) == 3


def test_an_empty_score_is_refused():
    for blank in ("", "   ", "|"):
        with pytest.raises(th.ParseError):
            sq.parse_score(blank)


def test_an_unknown_token_names_itself_and_suggests_the_syntax():
    with pytest.raises(th.ParseError) as excinfo:
        sq.parse_score("4C 麒麟 4E")
    message = str(excinfo.value)
    assert "麒麟" in message and "4C" in message


def test_render_steps_convert_to_seconds_for_the_synth():
    score = sq.parse_score("4C 4E/8")
    steps = sq.to_render_steps(score, 120)
    assert steps[0][0] == [60]
    assert steps[0][1] == pytest.approx(0.5)
    assert steps[1][1] == pytest.approx(0.25)
