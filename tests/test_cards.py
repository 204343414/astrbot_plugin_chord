"""Card layouts and the Hub contract.

QQ refuses a keyboard larger than 5x5, and it refuses it at send time with an
opaque error -- so the limit is checked here rather than discovered in a group.
"""
import sys
from pathlib import Path

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
