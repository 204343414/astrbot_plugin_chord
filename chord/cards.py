"""Card layouts for the chord tool.

QQ allows at most 5 rows x 5 columns = 25 buttons, which is the constraint
that shapes everything here. 12 roots x 12 qualities is 144 combinations, so a
single card cannot offer them all: the flow is **pick a root, then pick a
quality**, two taps, each on a card that fits comfortably.

Pure data -- no AstrBot, no Hub, no numpy.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .theory import ARPEGGIOS, QUALITIES, SHARP_NAMES, Chord, midi_to_name
from .synth import WAVEFORMS

#: The compose command every blue-text sequence must start with.
COMPOSE_COMMAND = "/编曲"

#: MIDI tops out at 127 = G9, so A9 and B9 are not playable pitches.
LOWEST_OCTAVE = 1
HIGHEST_OCTAVE = 9
HIGHEST_OCTAVE_NOTES = ("C", "D", "E", "F", "G")

#: Tempi the BPM button cycles through. Covers ballad to drum-and-bass without
#: making the user tap thirty times to cross the range.
BPM_CHOICES = (60, 80, 90, 100, 120, 140, 160, 180)

#: Drum voices, as tokens the sequence parser will understand.
DRUM_TOKENS = (
    ("K", "🥁 底鼓", "kick"),
    ("S", "🪘 军鼓", "snare"),
    ("H", "🎩 闭镲", "hihat"),
    ("O", "💿 开镲", "openhat"),
)

#: Roots laid out as they sit on a keyboard: naturals on one row, accidentals
#: above them, so the shape is familiar even to someone who cannot read music.
NATURAL_ROW = ("C", "D", "E", "F", "G", "A", "B")
SHARP_ROW = ("C#", "D#", "F#", "G#", "A#")

TITLE = "🎵 吟游诗人"


def blue(text: str, show: str | None = None) -> str:
    """A ``<qqbot-cmd-input>`` tag: tapping it *appends* to the input box.

    Verified in a live group: consecutive taps accumulate rather than
    replace, and QQ adds the @bot mention only once. That is what makes a
    melody typable by tapping -- and why note tokens carry no leading slash,
    only the opening command does.

    ``show`` and ``reference`` are omitted when redundant: spelling them out
    costs ~28 characters per tag, and 63 notes would blow the 4000-character
    markdown budget.
    """
    if show is None or show == text:
        return f'<qqbot-cmd-input text="{quote(text)}" />'
    return f'<qqbot-cmd-input text="{quote(text)}" show="{quote(show)}" />'


def _safe_id(text: str) -> str:
    """Make a button id the Hub will accept.

    The Hub only allows ``[A-Za-z0-9_.:-]`` in ids, so "root_C#" was rejected
    outright with "按钮 ID 含非法字符". Sharps are spelled out rather than
    dropped, because dropping them would make C and C# collide -- two buttons
    with one id, and the wrong chord would play.
    """
    return text.replace("#", "s").replace("b", "f")


def _button(button_id: str, label: str, action: str,
            params: dict[str, Any] | None = None, style: int = 0) -> dict:
    return {
        "id": button_id,
        "label": label,
        "style": style,
        "action_id": action,
        "params": params or {},
        "one_shot": False,
    }


def build_root_card(waveform: str = "square") -> dict[str, Any]:
    """Step one: choose a root note.

    Five accidentals on top, seven naturals below -- 12 buttons, well inside
    the 5x5 limit, and shaped like the piano keys they represent.
    """
    rows = [
        [_button(f"root_{_safe_id(name)}", name, "chord.pick_root",
                 {"root": name})
         for name in SHARP_ROW],
        [_button(f"root_{_safe_id(name)}", name, "chord.pick_root",
                 {"root": name}, style=1)
         for name in NATURAL_ROW[:4]],
        [_button(f"root_{_safe_id(name)}", name, "chord.pick_root",
                 {"root": name}, style=1)
         for name in NATURAL_ROW[4:]],
        [
            _button("wave", f"🔊 音色：{WAVEFORMS[waveform]}",
                    "chord.cycle_waveform", {}),
            _button("help", "❓ 用法", "chord.help", {}),
        ],
    ]
    return {
        "id": "chord_root",
        "markdown": "\n".join([
            f"# {TITLE}",
            "选一个**根音**，下一步选和弦类型。",
            "",
            "也可以直接打字：`/和弦 Cmaj7`、`/和弦 F#m7`、`/单音 C4 E4 G4`",
        ]),
        "rows": rows,
        "one_shot": False,
        "ttl_seconds": 3600,
    }


def build_quality_card(root: str, waveform: str = "square") -> dict[str, Any]:
    """Step two: choose the quality for ``root``."""
    rows: list[list[dict]] = []
    row: list[dict] = []
    for quality in QUALITIES:
        suffix = "" if quality.key == "maj" else quality.key
        row.append(_button(
            f"q_{_safe_id(quality.key)}", f"{root}{suffix}", "chord.play",
            {"root": root, "quality": quality.key}, style=1,
        ))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append([
        _button("back", "← 换根音", "chord.open", {}),
        _button("wave", f"🔊 {WAVEFORMS[waveform]}", "chord.cycle_waveform", {}),
    ])
    return {
        "id": "chord_quality",
        "markdown": "\n".join([
            f"# {TITLE} · 根音 {root}",
            "选一个和弦类型，机器人会**弹给你听**并列出构成音。",
        ]),
        "rows": rows,
        "one_shot": False,
        "ttl_seconds": 3600,
    }


def build_result_card(chord: Chord, waveform: str,
                      voice_format: str = "") -> dict[str, Any]:
    """Shown next to the voice message: what was played, and what to try next."""
    root = SHARP_NAMES[chord.root % 12]
    degrees = " ".join(
        f"{midi_to_name(note)}" for note in chord.notes
    )
    intervals = " ".join(str(step) for step in chord.quality.intervals)

    rows = [
        [_button(f"arp_{_safe_id(key)}", label, "chord.arpeggio",
                 {"root": root, "quality": chord.quality.key, "pattern": key})
         for key, (label, _) in list(ARPEGGIOS.items())[1:4]],
        [
            _button("back", "← 换和弦", "chord.pick_root", {"root": root},
                    style=1),
            _button("home", "🏠 主菜单", "chord.open", {}),
        ],
    ]
    lines = [
        f"# {chord.name}　{chord.quality.label}",
        f"**构成音**：{degrees}",
        f"**音程**：根音 +{intervals} 半音",
        f"**音色**：{WAVEFORMS.get(waveform, waveform)}",
    ]
    if voice_format:
        lines.append(f"<small>编码 {voice_format}</small>")
    return {
        "id": "chord_result",
        "markdown": "\n".join(lines),
        "rows": rows,
        "one_shot": False,
        "ttl_seconds": 3600,
    }


def build_help_card() -> dict[str, Any]:
    return {
        "id": "chord_help",
        "markdown": "\n".join([
            f"# {TITLE} · 用法",
            "",
            "**记谱规则**：字母后面跟**数字是八度**，跟**字母是和弦**。",
            "",
            "| 输入 | 含义 |",
            "| --- | --- |",
            "| `C` | 单音 C4（中央 C） |",
            "| `C5` | 单音 C5，高一个八度 |",
            "| `Cmaj` / `C` | C 大三和弦 |",
            "| `Cm` / `Cmin` | C 小三和弦（**小写 m**） |",
            "| `G7` | G 属七和弦（不是 G 的第 7 八度） |",
            "| `F#m7` | 升 F 小七和弦 |",
            "",
            "命令：`/和弦 Am7`　`/单音 C4 E4 G4`　`/吟游诗人` 打开面板",
        ]),
        "rows": [[_button("home", "🏠 返回", "chord.open", {}, style=1)]],
        "one_shot": False,
        "ttl_seconds": 1800,
    }


def build_note_card(waveform: str = "square", bpm: int = 120) -> dict[str, Any]:
    """The single-note page: every playable pitch as tappable blue text.

    Notes are written **octave first** (``4C``, ``7G``). Letter-first would
    make ``G7`` mean both "G in octave 7" and "G dominant seventh"; no
    precedence rule can satisfy both, so the grammar sidesteps it.

    Accidentals and durations are *buttons* rather than blue text: they
    modify the note just typed, and there are far too many combinations to
    spell out (63 pitches x 5 durations would need 315 tags).
    """
    lines = [
        "# 🎵 吟游诗人 · 单音",
        "",
        f"{blue(COMPOSE_COMMAND + ' ', '▶ 开始编曲')}　← 先点这个，再点音符，"
        "攒够一句自己按发送",
        "",
        "*八度在前*：`4C` 是中央 C，`7G` 是高音 G。",
        "",
    ]
    for octave in range(LOWEST_OCTAVE, HIGHEST_OCTAVE + 1):
        names = (HIGHEST_OCTAVE_NOTES if octave == HIGHEST_OCTAVE
                 else NATURAL_ROW)
        row = "".join(blue(f"{octave}{name} ") for name in names)
        lines.append(f"**{octave}** {row}")

    rows = [
        [_button(f"sharp_{_safe_id(name)}", name, "chord.note_hint",
                 {"kind": "sharp", "value": name})
         for name in SHARP_ROW],
        [_button("dur_2", "𝅗𝅥 二分", "chord.note_hint", {"kind": "dur", "value": "/2"}),
         _button("dur_4", "♩ 四分", "chord.note_hint", {"kind": "dur", "value": "/4"}),
         _button("dur_8", "♪ 八分", "chord.note_hint", {"kind": "dur", "value": "/8"}),
         _button("dur_16", "𝅘𝅥𝅯 十六", "chord.note_hint", {"kind": "dur", "value": "/16"}),
         _button("dur_3", "⑶ 三连", "chord.note_hint", {"kind": "dur", "value": "/3"})],
        [_button("dur_dot", "· 附点", "chord.note_hint", {"kind": "dur", "value": "."}),
         _button("rest", "𝄽 休止", "chord.note_hint", {"kind": "rest", "value": "-"}),
         _button("bar", "▌小节线", "chord.note_hint", {"kind": "bar", "value": "|"}),
         _button("bpm", f"⏱ BPM {bpm}", "chord.cycle_bpm", {}),
         _button("wave", f"🔊 {WAVEFORMS[waveform]}", "chord.cycle_waveform", {})],
        [_button("home", "🏠 主菜单", "chord.open", {}, style=1),
         _button("help", "❓ 记谱规则", "chord.help", {})],
    ]
    return {
        "id": "chord_notes",
        "markdown": "\n".join(lines),
        "rows": rows,
        "one_shot": False,
        "ttl_seconds": 3600,
    }


def build_home_card(waveform: str = "square", bpm: int = 120) -> dict[str, Any]:
    """The main menu: three sub-tools sharing one tempo and timbre."""
    return {
        "id": "chord_home",
        "markdown": "\n".join([
            f"# {TITLE}",
            "",
            f"当前：**BPM {bpm}** · 音色 **{WAVEFORMS.get(waveform, waveform)}**",
            "",
            "| 子面板 | 做什么 |",
            "| --- | --- |",
            "| 🎼 单音 | 点蓝字攒旋律，支持时值与三连音 |",
            "| 🎹 和弦 | 选根音与和弦类型，直接试听 |",
            "| 🥁 鼓点 | 底鼓 / 军鼓 / 踩镲（开发中） |",
        ]),
        "rows": [
            [_button("go_notes", "🎼 单音", "chord.notes", {}, style=1),
             _button("go_chord", "🎹 和弦", "chord.chords", {}, style=1),
             _button("go_drum", "🥁 鼓点", "chord.drums", {}, style=1)],
            [_button("bpm", f"⏱ BPM {bpm}", "chord.cycle_bpm", {}),
             _button("wave", f"🔊 {WAVEFORMS.get(waveform, waveform)}",
                     "chord.cycle_waveform", {}),
             _button("help", "❓ 用法", "chord.help", {})],
        ],
        "one_shot": False,
        "ttl_seconds": 3600,
    }


def build_drum_card(bpm: int = 120) -> dict[str, Any]:
    """The drum page. Same blue-text mechanic as notes, different alphabet."""
    lines = [
        "# 🥁 吟游诗人 · 鼓点",
        "",
        f"{blue(COMPOSE_COMMAND + ' ', '▶ 开始编曲')}　← 先点这个，再点鼓件",
        "",
        f"当前 **BPM {bpm}**。鼓件与音符可以混写在同一句里。",
        "",
    ]
    for token, label, _name in DRUM_TOKENS:
        row = "".join(blue(f"{token}{suffix} ", f"{token}{suffix}")
                      for suffix in ("", "/8", "/16"))
        lines.append(f"**{label}** {row}")
    lines.append("")
    lines.append(f"休止 {blue('- ')}　小节线 {blue('| ')}")

    rows = [
        [_button("pat_basic", "▌ 基本节奏", "chord.drum_pattern",
                 {"pattern": "basic"}, style=1),
         _button("pat_rock", "🎸 摇滚", "chord.drum_pattern", {"pattern": "rock"},
                 style=1),
         _button("pat_disco", "🕺 迪斯科", "chord.drum_pattern",
                 {"pattern": "disco"}, style=1)],
        [_button("bpm", f"⏱ BPM {bpm}", "chord.cycle_bpm", {}),
         _button("home", "🏠 主菜单", "chord.open", {}, style=1),
         _button("help", "❓ 记谱规则", "chord.help", {})],
    ]
    return {
        "id": "chord_drums",
        "markdown": "\n".join(lines),
        "rows": rows,
        "one_shot": False,
        "ttl_seconds": 3600,
    }
