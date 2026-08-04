"""Card layouts for the chord tool.

QQ allows at most 5 rows x 5 columns = 25 buttons, which is the constraint
that shapes everything here. 12 roots x 12 qualities is 144 combinations, so a
single card cannot offer them all: the flow is **pick a root, then pick a
quality**, two taps, each on a card that fits comfortably.

Pure data -- no AstrBot, no Hub, no numpy.
"""
from __future__ import annotations

from typing import Any

from .theory import ARPEGGIOS, QUALITIES, SHARP_NAMES, Chord, midi_to_name
from .synth import WAVEFORMS

#: Roots laid out as they sit on a keyboard: naturals on one row, accidentals
#: above them, so the shape is familiar even to someone who cannot read music.
NATURAL_ROW = ("C", "D", "E", "F", "G", "A", "B")
SHARP_ROW = ("C#", "D#", "F#", "G#", "A#")

TITLE = "🎵 吟游诗人"


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
        [_button(f"root_{name}", name, "chord.pick_root", {"root": name})
         for name in SHARP_ROW],
        [_button(f"root_{name}", name, "chord.pick_root", {"root": name},
                 style=1)
         for name in NATURAL_ROW[:4]],
        [_button(f"root_{name}", name, "chord.pick_root", {"root": name},
                 style=1)
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
            f"q_{quality.key}", f"{root}{suffix}", "chord.play",
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
        [_button(f"arp_{key}", label, "chord.arpeggio",
                 {"root": root, "quality": chord.quality.key, "pattern": key})
         for key, (label, _) in list(ARPEGGIOS.items())[1:4]],
        [
            _button("again", "🔁 再听一次", "chord.play",
                    {"root": root, "quality": chord.quality.key}, style=1),
            _button("back", "← 换和弦", "chord.pick_root", {"root": root}),
            _button("home", "🏠 换根音", "chord.open", {}),
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
