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


def _insert(button_id: str, label: str, text: str, style: int = 0) -> dict:
    """A type=2 button: appends ``text`` to the input box, sends nothing.

    Used for marks that get tapped over and over while writing a phrase. As
    type=1 callbacks they would each cost a round trip *and* a passive reply,
    so five taps would exhaust the five-message budget mid-melody.
    """
    return {
        "id": button_id,
        "label": label,
        "style": style,
        "insert_text": text,
        "one_shot": False,
    }


def build_root_card(waveform: str = "square") -> dict[str, Any]:
    """Step one: choose a root note.

    Naturals are buttons; the black keys come from the ♯/♭ pair rather than
    a row of their own, which keeps every row to four so QQ does not shrink
    the labels until they are unreadable.
    """
    rows = [
        [_button(f"root_{name}", name, "chord.pick_root", {"root": name},
                 style=1)
         for name in NATURAL_ROW[:4]],
        [_button(f"root_{name}", name, "chord.pick_root", {"root": name},
                 style=1)
         for name in NATURAL_ROW[4:]],
        [_button("root_Cs", "C#", "chord.pick_root", {"root": "C#"}),
         _button("root_Ds", "D#", "chord.pick_root", {"root": "D#"}),
         _button("root_Fs", "F#", "chord.pick_root", {"root": "F#"}),
         _button("root_Gs", "G#", "chord.pick_root", {"root": "G#"})],
        [_button("root_As", "A#", "chord.pick_root", {"root": "A#"}),
         _button("wave", f"🔊 {WAVEFORMS[waveform]}", "chord.pick_waveform", {}),
         _button("home", "🏠 主菜单", "chord.open", {}),
         _button("help", "❓ 用法", "chord.help", {})],
    ]
    return {
        "id": "chord_root",
        "markdown": "\n".join([
            f"# {TITLE} · 和弦",
            "选一个**根音**，下一步选和弦类型。",
            "",
            "也可以直接打字：`/和弦 Cmaj7`、`/和弦 F#m7`",
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
        _button("back", "← 换根音", "chord.chords", {}),
        _button("wave", f"🔊 {WAVEFORMS[waveform]}", "chord.pick_waveform", {}),
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

    Accidentals are two buttons, not ten. Tapping ♯ then ``4C`` yields
    ``#4C``, which the parser accepts -- so both the sharp-minded and the
    flat-minded get their own spelling from one pair of keys, instead of the
    card carrying a C#/D#/F#/G#/A# row that only serves half of them.

    Rows are kept short on purpose: QQ shrinks labels to fit, and a row of
    five was clipping the text.
    """
    lines = [
        "# 🎵 吟游诗人 · 单音",
        "",
        f"{blue(COMPOSE_COMMAND + ' ', '▶ 开始编曲')}　← 先点这个，再点音符，"
        "攒够一句自己按发送",
        "",
        "*八度在前*：`4C` 是中央 C。想要黑键先点 **♯** 或 **♭**，再点音名。",
        "",
    ]
    for octave in range(LOWEST_OCTAVE, HIGHEST_OCTAVE + 1):
        names = (HIGHEST_OCTAVE_NOTES if octave == HIGHEST_OCTAVE
                 else NATURAL_ROW)
        row = "".join(blue(f"{octave}{name} ") for name in names)
        lines.append(f"**{octave}** {row}")

    rows = [
        # Marks that get tapped constantly: type=2, so they cost no round trip
        # and no passive reply.
        [_insert("acc_sharp", "♯ 升", "#", style=1),
         _insert("acc_flat", "♭ 降", "b", style=1),
         _insert("mark_dot", "· 附点", "."),
         _insert("mark_rest", "𝄽 休止", "- ")],
        [_insert("dur_2", "𝅗𝅥 二分", "/2 "),
         _insert("dur_8", "♪ 八分", "/8 "),
         _insert("dur_16", "𝅘𝅥𝅯 十六", "/16 "),
         _insert("dur_3", "⑶ 三连", "/3 ")],
        [_insert("mark_bar", "▌小节线", "| "),
         _button("bpm", f"⏱ BPM {bpm}", "chord.pick_bpm", {}),
         _button("wave", f"🔊 {WAVEFORMS[waveform]}", "chord.pick_waveform", {})],
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


def build_waveform_card(current: str = "square") -> dict[str, Any]:
    """Pick a timbre directly instead of cycling through them.

    Cycling needed up to three taps -- and three cards -- to reach the one you
    wanted, each costing a passive reply.
    """
    rows = [[
        _button(f"w_{key}", f"{'✅ ' if key == current else ''}{label}",
                "chord.set_waveform", {"waveform": key},
                style=1 if key == current else 0)
        for key, label in WAVEFORMS.items()
    ], [_button("back", "← 返回", "chord.open", {})]]
    return {
        "id": "chord_waveform",
        "markdown": "\n".join([
            "# 🔊 选择音色",
            "",
            "四种经典 8-bit 波形。方波最亮，正弦最柔。",
        ]),
        "rows": rows,
        "one_shot": False,
        "ttl_seconds": 1800,
    }


def build_bpm_card(current: int = 120) -> dict[str, Any]:
    """Pick a tempo directly, same reasoning as the timbre picker."""
    rows: list[list[dict]] = []
    row: list[dict] = []
    for value in BPM_CHOICES:
        row.append(_button(
            f"bpm_{value}", f"{'✅ ' if value == current else ''}{value}",
            "chord.set_bpm", {"bpm": value},
            style=1 if value == current else 0))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([_button("back", "← 返回", "chord.open", {})])
    return {
        "id": "chord_bpm",
        "markdown": "\n".join([
            "# ⏱ 选择速度",
            "",
            f"当前 **BPM {current}**。BPM 指每分钟多少个**四分音符**，"
            "所以每秒 4 下就是 BPM 240——但通常写成 BPM 120 弹八分音符。",
        ]),
        "rows": rows,
        "one_shot": False,
        "ttl_seconds": 1800,
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
            [_button("bpm", f"⏱ BPM {bpm}", "chord.pick_bpm", {}),
             _button("wave", f"🔊 {WAVEFORMS.get(waveform, waveform)}",
                     "chord.pick_waveform", {}),
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
        [_button("bpm", f"⏱ BPM {bpm}", "chord.pick_bpm", {}),
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
