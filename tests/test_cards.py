"""Card layouts and the Hub contract.

QQ refuses a keyboard larger than 5x5, and it refuses it at send time with an
opaque error -- so the limit is checked here rather than discovered in a group.
"""
import re
import sys
from pathlib import Path
from urllib.parse import unquote

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chord import cards  # noqa: E402
from chord import synth  # noqa: E402
from chord import theory as th  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

ALL_CARDS = {
    "root": cards.build_root_card(),
    "quality": cards.build_quality_card("C"),
    "result": cards.build_result_card(th.parse_chord("Cmaj7"), "square", "silk"),
    "help": cards.build_help_card(),
}


@pytest.mark.parametrize("name", sorted(ALL_CARDS))
def test_every_card_fits_qq_five_by_five(name):
    rows = ALL_CARDS[name]["rows"]
    assert len(rows) <= 5, f"{name} 超过 5 行"
    for row in rows:
        assert len(row) <= 5, f"{name} 某行超过 5 个按钮"


@pytest.mark.parametrize("name", sorted(ALL_CARDS))
def test_every_card_has_a_title_and_no_empty_row(name):
    card = ALL_CARDS[name]
    assert card["markdown"].startswith("#")
    assert all(row for row in card["rows"])


@pytest.mark.parametrize("name", sorted(ALL_CARDS))
def test_no_button_is_one_shot(name):
    """The Hub burns a one-shot click before the plugin runs, so a panel
    button marked one_shot would die on its first press."""
    for row in ALL_CARDS[name]["rows"]:
        for button in row:
            assert button.get("one_shot") is False, button["id"]


@pytest.mark.parametrize("name", sorted(ALL_CARDS))
def test_button_ids_are_unique_within_a_card(name):
    ids = [b["id"] for row in ALL_CARDS[name]["rows"] for b in row]
    assert len(ids) == len(set(ids))


def test_the_root_card_offers_all_twelve_semitones():
    """A missing root would simply be unreachable by tapping."""
    labels = {b["label"] for row in cards.build_root_card()["rows"] for b in row}
    for name in th.SHARP_NAMES:
        assert name in labels, name


def test_the_quality_card_offers_every_quality():
    card = cards.build_quality_card("C")
    offered = {
        b["params"].get("quality")
        for row in card["rows"] for b in row
        if b["action_id"] == "chord.play"
    }
    assert offered == {q.key for q in th.QUALITIES}


def test_the_quality_card_labels_read_like_real_chord_names():
    card = cards.build_quality_card("F#")
    labels = [b["label"] for row in card["rows"] for b in row
              if b["action_id"] == "chord.play"]
    assert "F#" in labels, "大三和弦应显示为裸根音"
    assert "F#min7" in labels


def test_the_result_card_lists_the_actual_chord_tones():
    card = cards.build_result_card(th.parse_chord("Am7"), "square")
    for note in ("A4", "C5", "E5", "G5"):
        assert note in card["markdown"], note


def test_the_result_card_names_the_waveform_in_chinese():
    card = cards.build_result_card(th.parse_chord("C"), "triangle")
    assert synth.WAVEFORMS["triangle"] in card["markdown"]


def test_the_help_card_documents_the_digit_versus_quality_rule():
    """The one rule people get wrong: G7 is a chord, C5 is an octave."""
    markdown = cards.build_help_card()["markdown"]
    assert "G7" in markdown and "八度" in markdown
    assert "Cm" in markdown


def test_every_action_referenced_by_a_card_is_registered():
    """A card pointing at an unregistered action is a dead button."""
    source = (ROOT / "main.py").read_text("utf-8")
    for card in ALL_CARDS.values():
        for row in card["rows"]:
            for button in row:
                assert f'"{button["action_id"]}"' in source, button["action_id"]


def test_the_panel_rides_one_self_replacing_session():
    """Otherwise each tap leaves another card on screen."""
    source = (ROOT / "main.py").read_text("utf-8")
    assert "_ui_session" in source
    body = source[source.index("def _ui_session"):]
    body = body[: body.index("def _wave")]
    assert "origin" in body


def test_voice_uses_qq_file_type_three():
    source = (ROOT / "main.py").read_text("utf-8")
    assert "VOICE_FILE_TYPE = 3" in source


def test_the_plugin_requires_a_hub_new_enough_to_send_media():
    """send_media_message only exists from Hub v0.17.0; without the check the
    failure would surface as a bare AttributeError mid-click."""
    source = (ROOT / "main.py").read_text("utf-8")
    guard = source[source.index("missing = ["):]
    guard = guard[: guard.index("self._hub = hub")]
    assert "send_media_message" in guard
    assert "版本过旧" in guard


def test_parse_failures_explain_the_notation():
    """A bare '格式错误' teaches nobody; the reason is the whole value."""
    source = (ROOT / "main.py").read_text("utf-8")
    handler = source[source.index("except th.ParseError as exc:"):]
    handler = handler[: handler.index("return")]
    assert "{exc}" in handler


# --- how AstrBot actually imports this plugin -------------------------------

def test_main_uses_relative_imports_only():
    """AstrBot imports the plugin as ``data.plugins.<dir>.main``.

    The plugin directory is therefore *not* on sys.path, so ``from chord
    import ...`` raises ModuleNotFoundError at load time -- which is exactly
    how this shipped broken once. Only relative imports can work.
    """
    source = (ROOT / "main.py").read_text("utf-8")
    offenders = [
        line.strip() for line in source.splitlines()
        if line.startswith(("from chord", "import chord"))
    ]
    assert not offenders, f"必须用相对导入：{offenders}"
    assert "from .chord import" in source


def test_the_plugin_imports_the_way_astrbot_loads_it():
    """End-to-end: build the real package path and __import__ it.

    Checking the source text alone would not catch a submodule that still
    imports absolutely, so this actually performs the import.
    """
    import shutil
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "data" / "plugins" / "astrbot_plugin_chord"
        target.parent.mkdir(parents=True)
        shutil.copytree(ROOT, target,
                        ignore=shutil.ignore_patterns("__pycache__", ".git",
                                                      ".pytest_cache"))
        code = f'''
import sys, types
sys.path.insert(0, {tmp!r})
api = types.ModuleType("astrbot.api")
class _L:
    def __getattr__(self, _): return lambda *a, **k: None
api.logger = _L(); api.AstrBotConfig = dict
ev = types.ModuleType("astrbot.api.event")
class _Any:
    def __getattr__(self, n): return _Any()
    def __call__(self, *a, **k):
        if len(a) == 1 and callable(a[0]) and not k: return a[0]
        return lambda fn: fn
    def __or__(self, o): return self
ev.filter = _Any(); ev.AstrMessageEvent = object
star = types.ModuleType("astrbot.api.star")
star.Context = object; star.Star = object
star.register = lambda *a, **k: (lambda cls: cls)
root = types.ModuleType("astrbot"); root.api = api
sys.modules.update({{"astrbot": root, "astrbot.api": api,
                    "astrbot.api.event": ev, "astrbot.api.star": star}})
mod = __import__("data.plugins.astrbot_plugin_chord.main", fromlist=["main"])
assert mod.ChordPlugin
print("ok")
'''
        result = subprocess.run([sys.executable, "-B", "-c", code],
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr[-900:]


# --- the Hub's own validator ------------------------------------------------
#
# Cards were rejected at send time with "按钮 ID 含非法字符": the Hub allows only
# [A-Za-z0-9_.:-] in a button id, and every sharp root produced "root_C#".
# Checking the layout locally was not enough -- the contract lives in the Hub.

#: Mirrors qqofficial_hub.ephemeral.CARD_ID_RE.
HUB_ID_PATTERN = r"[A-Za-z0-9_.:-]{1,80}"


def _all_cards():
    """Every card this plugin can send, including the ones with sharps."""
    yield "root", cards.build_root_card()
    for waveform in synth.WAVEFORMS:
        yield f"root:{waveform}", cards.build_root_card(waveform)
    for root in th.SHARP_NAMES:
        yield f"quality:{root}", cards.build_quality_card(root)
    for text in ("C", "F#m7", "Bb7", "Cmaj7"):
        yield f"result:{text}", cards.build_result_card(
            th.parse_chord(text), "square", "silk")
    yield "help", cards.build_help_card()


def test_every_button_id_matches_the_hub_pattern():
    import re

    pattern = re.compile(HUB_ID_PATTERN)
    for name, card in _all_cards():
        for row in card["rows"]:
            for button in row:
                assert pattern.fullmatch(button["id"]), f"{name}: {button['id']}"
                assert pattern.fullmatch(button["action_id"]), name


def test_sharp_roots_keep_distinct_ids():
    """Stripping '#' instead of encoding it would collide C with C#."""
    ids = {b["label"]: b["id"]
           for row in cards.build_root_card()["rows"] for b in row}
    assert ids["C"] != ids["C#"]
    assert len(set(ids.values())) == len(ids)


def test_the_real_note_name_survives_in_the_params():
    """The id is sanitised; the payload must still say C#, not Cs."""
    for row in cards.build_root_card()["rows"]:
        for button in row:
            if button["action_id"] == "chord.pick_root":
                assert button["params"]["root"] == button["label"]


def test_cards_pass_the_hubs_own_validator():
    """Uses the Hub's validator, not a copy of its rules.

    A local re-implementation would have happily accepted "root_C#" too --
    which is exactly how this reached a live group.
    """
    ephemeral = pytest.importorskip(
        "qqofficial_hub.ephemeral",
        reason="需要 PYTHONPATH 指向 astrbot_plugin_qqofficial_hub",
    )
    for name, card in _all_cards():
        try:
            ephemeral.validate_card(card)
        except Exception as exc:  # noqa: BLE001 - report which card failed
            pytest.fail(f"{name} 未通过 Hub 校验: {type(exc).__name__}: {exc}")


# --- blue text (qqbot-cmd-input) --------------------------------------------
#
# Verified in a live group: consecutive taps APPEND to the input box and QQ
# adds the @bot mention only once. That is what lets a melody be assembled by
# tapping, and why note tokens carry no leading slash.

def test_blue_text_urlencodes_and_omits_redundant_attributes():
    """Spelling out show/reference costs ~28 chars per tag; 63 notes would
    then blow the 4000-character markdown budget."""
    tag = cards.blue("4C ")
    assert tag == '<qqbot-cmd-input text="4C%20" />'
    assert "show=" not in tag


def test_blue_text_keeps_show_when_it_differs():
    """A separate label is kept; '/' need not be escaped (both forms decode
    identically and both pass the Hub's validator)."""
    tag = cards.blue("/编曲 ", "▶ 开始编曲")
    assert "show=" in tag
    text = unquote(re.search(r'text="([^"]+)"', tag).group(1))
    assert text == "/编曲 "


def test_only_the_opening_command_carries_a_slash():
    """Note tokens must not, or the input box fills with /编曲 /编曲 /编曲."""
    card = cards.build_note_card()
    tags = re.findall(r'text="([^"]+)"', card["markdown"])
    decoded = [unquote(t) for t in tags]
    slashed = [t for t in decoded if t.startswith("/")]
    assert slashed == ["/编曲 "], f"只应有一个命令蓝字，实际 {slashed}"


def test_the_note_page_offers_every_playable_octave():
    card = cards.build_note_card()
    decoded = [unquote(t) for t in re.findall(r'text="([^"]+)"', card["markdown"])]
    for octave in range(1, 10):
        assert f"{octave}C " in decoded, f"缺少第 {octave} 八度"


def test_the_note_page_stops_at_g9_because_midi_does():
    card = cards.build_note_card()
    decoded = [unquote(t).strip() for t in
               re.findall(r'text="([^"]+)"', card["markdown"])]
    assert "9G" in decoded
    for impossible in ("9A", "9B"):
        assert impossible not in decoded, f"{impossible} 超出 MIDI 127"


def test_every_blue_token_actually_parses():
    """A tag that inserts something the parser rejects is a trap."""
    from chord import sequence as sq

    for builder in (cards.build_note_card, cards.build_drum_card):
        card = builder()
        for encoded in re.findall(r'text="([^"]+)"', card["markdown"]):
            token = unquote(encoded).strip()
            if token.startswith("/"):
                continue
            if token in ("|", "-"):
                continue
            sq.parse_token(token)      # raises if the grammar disagrees


def test_the_pages_stay_inside_the_markdown_budget():
    for name, builder in (("notes", cards.build_note_card),
                          ("drums", cards.build_drum_card),
                          ("home", cards.build_home_card)):
        assert len(builder()["markdown"]) <= 4000, name


def test_bpm_choices_are_sorted_and_musical():
    assert list(cards.BPM_CHOICES) == sorted(cards.BPM_CHOICES)
    assert 120 in cards.BPM_CHOICES
