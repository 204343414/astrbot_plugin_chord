"""吟游诗人 -- a chord sounder for QQ Official groups.

Two taps produce a sound: pick a root, pick a quality, and the bot sends a
synthesised voice message plus a card listing the chord tones.

Design notes
------------
* Audio is generated from scratch every time (``chord/synth.py``), never by
  stitching previously-sent clips. Re-encoding an already-encoded clip loses
  quality on every pass; rendering from the note list loses it exactly once.
* Sound needs **no ffmpeg** -- a waveform is an array of numbers and WAV is a
  stdlib container. ``graiax-silkcoder`` is optional and only makes the upload
  ~5x smaller.
* Cards ride one Hub session per group, so each new card recalls the one it
  replaces instead of stacking up.
"""
from __future__ import annotations

from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

# Relative imports are mandatory: AstrBot imports a plugin as
# ``data.plugins.<dir>.main`` (star_manager: path = "data.plugins." +
# root_dir_name + "." + module_str), so "chord" is never on sys.path and an
# absolute import fails with ModuleNotFoundError at load time.
from .chord import cards, synth
from .chord import theory as th

PLUGIN_NAME = "astrbot_plugin_chord"
HUB_NAME = "astrbot_plugin_qqofficial_hub"
OWNER = PLUGIN_NAME

#: QQ's own numbering for rich media; 3 is voice.
VOICE_FILE_TYPE = 3


@register(
    PLUGIN_NAME,
    "204343414",
    "QQ 官方机器人吟游诗人：点按钮听和弦，8-bit 合成，附构成音与分解型。",
    "0.1.0",
    "https://github.com/204343414/astrbot_plugin_chord",
)
class ChordPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None) -> None:
        super().__init__(context)
        self.context = context
        self.config = config or {}
        self.duration = max(float(self.config.get("chord_seconds", 1.6)), 0.3)
        self.arp_step = max(float(self.config.get("arpeggio_step_seconds", 0.3)), 0.1)
        #: origin -> waveform. In memory: a preference, not a document.
        self._waveform: dict[str, str] = {}
        self._hub = None

    async def initialize(self) -> None:
        self._register_actions()
        if not synth.silk_available():
            logger.info(
                "[Chord] 未安装 graiax-silkcoder，将发送 WAV（体积约大 5 倍）"
            )

    async def terminate(self) -> None:
        hub = self._get_hub(quiet=True)
        if hub is not None:
            try:
                hub.actions.unregister_owner(OWNER)
            except Exception:
                logger.warning("[Chord] Failed to unregister actions")

    # --- Hub plumbing -------------------------------------------------------

    def _get_hub(self, quiet: bool = False):
        if self._hub is not None:
            return self._hub
        star = self.context.get_registered_star(HUB_NAME)
        if star is None:
            if not quiet:
                logger.error("[Chord] 未找到插件 %s，请确认已安装并启用", HUB_NAME)
            return None
        if not getattr(star, "activated", True):
            if not quiet:
                logger.error("[Chord] 插件 %s 已安装但未启用", HUB_NAME)
            return None
        # StarMetadata.star_cls is the plugin *instance*; there is no
        # star_cls_obj, and guessing that name once produced a bogus
        # "Hub not installed" on a perfectly good install.
        hub = getattr(star, "star_cls", None)
        if hub is None:
            if not quiet:
                logger.error("[Chord] %s 尚未完成初始化", HUB_NAME)
            return None
        missing = [name for name in ("send_ephemeral_card", "send_media_message",
                                     "actions") if not hasattr(hub, name)]
        if missing:
            if not quiet:
                logger.error("[Chord] %s 版本过旧，缺少 %s，请升级到 v0.17.0 以上",
                             HUB_NAME, "、".join(missing))
            return None
        self._hub = hub
        return hub

    @staticmethod
    def _hub_module(hub: Any, name: str):
        """Import a Hub submodule without hard-coding its directory name.

        AstrBot imports plugins as ``data.plugins.<dir>.main``, and the
        directory differs between a git clone and a downloaded zip, so the
        package is derived from the live instance -- by stripping the trailing
        module, not by taking the first segment (which yields a useless
        ``data``).
        """
        import importlib

        package = type(hub).__module__.rsplit(".", 1)[0]
        return importlib.import_module(f"{package}.qqofficial_hub.{name}")

    def _register_actions(self) -> None:
        hub = self._get_hub()
        if hub is None:
            return
        ActionSpec = self._hub_module(hub, "action_registry").ActionSpec

        specs = [
            ("chord.open", "🎵 吟游诗人", "打开和弦面板，点按钮听和弦。",
             self._act_open),
            ("chord.pick_root", "吟游诗人：选根音", "由面板触发。", self._act_pick_root),
            ("chord.play", "吟游诗人：播放和弦", "由面板触发，发送语音。",
             self._act_play),
            ("chord.arpeggio", "吟游诗人：分解和弦", "按分解型逐音播放。",
             self._act_arpeggio),
            ("chord.cycle_waveform", "吟游诗人：切换音色", "方波/锯齿/三角/正弦。",
             self._act_cycle_waveform),
            ("chord.help", "吟游诗人：用法", "显示记谱规则。", self._act_help),
        ]
        for action_id, title, description, callback in specs:
            hub.actions.register(ActionSpec(
                action_id=action_id,
                title=title,
                description=description,
                owner=OWNER,
                default_permission="everyone",
                callback=callback,
            ))
        logger.info("[Chord] Registered %d Hub actions", len(specs))

    def _ui_session(self, origin: str) -> str:
        """One self-replacing card per group, so the panel never stacks up."""
        return f"ui:chord:{origin}"

    def _wave(self, origin: str) -> str:
        return self._waveform.get(origin, synth.DEFAULT_WAVEFORM)

    async def _send_card(self, context, card: dict[str, Any]) -> None:
        hub = self._get_hub()
        if hub is None:
            raise RuntimeError("QQ Official Hub 不可用")
        passive_event_id = self._hub_module(hub, "passive_reply").passive_event_id
        await hub.send_ephemeral_card(
            context.origin,
            card,
            client=context.client,
            session_id=self._ui_session(context.origin),
            event_id=passive_event_id(context.interaction),
            initiator_openid=context.member_openid,
        )

    async def _send_voice(self, origin: str, signal, client=None,
                          interaction=None, msg_id: str | None = None) -> str:
        """Encode and upload. Returns the format actually used."""
        hub = self._get_hub()
        if hub is None:
            raise RuntimeError("QQ Official Hub 不可用")
        data, voice_format = synth.to_voice(signal)
        event_id = ""
        if interaction is not None:
            event_id = self._hub_module(hub, "passive_reply").passive_event_id(
                interaction)
        await hub.send_media_message(
            origin, data, VOICE_FILE_TYPE,
            client=client, event_id=event_id or None, msg_id=msg_id,
        )
        return voice_format

    # --- actions ------------------------------------------------------------

    async def _act_open(self, context, params) -> int:
        try:
            await self._send_card(
                context, cards.build_root_card(self._wave(context.origin)))
        except Exception:
            logger.exception("[Chord] Failed to open the panel")
            return 1
        return 0

    async def _act_pick_root(self, context, params) -> int:
        root = str(params.get("root") or "C")
        try:
            th.pitch_class(root)
        except th.ParseError:
            return 1
        try:
            await self._send_card(
                context, cards.build_quality_card(root, self._wave(context.origin)))
        except Exception:
            logger.exception("[Chord] Failed to show qualities")
            return 1
        return 0

    async def _act_play(self, context, params) -> int:
        try:
            chord = th.build_chord(str(params.get("root") or "C"),
                                   str(params.get("quality") or "maj"))
        except th.ParseError:
            return 1
        waveform = self._wave(context.origin)
        try:
            signal = synth.render_notes(list(chord.notes), self.duration, waveform)
            voice_format = await self._send_voice(
                context.origin, signal,
                client=context.client, interaction=context.interaction)
            await self._send_card(
                context, cards.build_result_card(chord, waveform, voice_format))
        except Exception:
            logger.exception("[Chord] Failed to play %s", chord.name)
            return 1
        return 0

    async def _act_arpeggio(self, context, params) -> int:
        try:
            chord = th.build_chord(str(params.get("root") or "C"),
                                   str(params.get("quality") or "maj"))
            order = th.arpeggio_order(chord, str(params.get("pattern") or "up"))
        except th.ParseError:
            return 1
        waveform = self._wave(context.origin)
        try:
            steps = [([note], self.arp_step) for note in order]
            signal = synth.render_sequence(steps, waveform)
            await self._send_voice(context.origin, signal,
                                   client=context.client,
                                   interaction=context.interaction)
        except Exception:
            logger.exception("[Chord] Failed to arpeggiate")
            return 1
        return 0

    async def _act_cycle_waveform(self, context, params) -> int:
        names = list(synth.WAVEFORMS)
        current = self._wave(context.origin)
        nxt = names[(names.index(current) + 1) % len(names)]
        self._waveform[context.origin] = nxt
        try:
            await self._send_card(context, cards.build_root_card(nxt))
        except Exception:
            logger.exception("[Chord] Failed to switch waveform")
            return 1
        return 0

    async def _act_help(self, context, params) -> int:
        try:
            await self._send_card(context, cards.build_help_card())
        except Exception:
            logger.exception("[Chord] Failed to show help")
            return 1
        return 0

    # --- chat commands ------------------------------------------------------

    @filter.platform_adapter_type(
        filter.PlatformAdapterType.QQOFFICIAL
        | filter.PlatformAdapterType.QQOFFICIAL_WEBHOOK
    )
    @filter.command("吟游诗人", alias={"chord", "和弦面板"})
    async def open_panel(self, event: AstrMessageEvent):
        """/吟游诗人 —— 打开和弦面板。"""
        event.stop_event()
        origin = str(getattr(event, "unified_msg_origin", "") or "")
        if "GroupMessage" not in origin:
            yield event.plain_result("吟游诗人只能在 QQ 官方群里用。")
            return
        hub = self._get_hub()
        if hub is None:
            yield event.plain_result("需要先安装并启用 QQ Official Hub 插件。")
            return
        try:
            await hub.send_ephemeral_card(
                origin,
                cards.build_root_card(self._wave(origin)),
                session_id=self._ui_session(origin),
                msg_id=str(event.message_obj.message_id or "") or None,
                initiator_openid=str(event.get_sender_id() or ""),
            )
        except Exception as exc:
            logger.exception("[Chord] Failed to send the panel")
            yield event.plain_result(f"发牌失败：{type(exc).__name__}: {exc}")

    @filter.platform_adapter_type(
        filter.PlatformAdapterType.QQOFFICIAL
        | filter.PlatformAdapterType.QQOFFICIAL_WEBHOOK
    )
    @filter.command("和弦", alias={"chordplay"})
    async def play_from_command(self, event: AstrMessageEvent, text: str = ""):
        """/和弦 Cmaj7 —— 直接弹一个和弦。"""
        event.stop_event()
        async for result in self._sound(event, text, as_chord=True):
            yield result

    @filter.platform_adapter_type(
        filter.PlatformAdapterType.QQOFFICIAL
        | filter.PlatformAdapterType.QQOFFICIAL_WEBHOOK
    )
    @filter.command("单音", alias={"note", "notes"})
    async def notes_from_command(self, event: AstrMessageEvent, text: str = ""):
        """/单音 C4 E4 G4 —— 直接弹一组单音。"""
        event.stop_event()
        async for result in self._sound(event, text, as_chord=False):
            yield result

    async def _sound(self, event: AstrMessageEvent, text: str, as_chord: bool):
        origin = str(getattr(event, "unified_msg_origin", "") or "")
        if "GroupMessage" not in origin:
            yield event.plain_result("吟游诗人只能在 QQ 官方群里用。")
            return
        raw = str(text or "").strip()
        if not raw:
            yield event.plain_result(
                "用法：`/和弦 Cmaj7` 或 `/单音 C4 E4 G4`；`/吟游诗人` 打开面板。")
            return
        if self._get_hub() is None:
            yield event.plain_result("需要先安装并启用 QQ Official Hub 插件。")
            return

        waveform = self._wave(origin)
        try:
            if as_chord:
                chord = th.parse_chord(raw)
                notes, caption = list(chord.notes), chord.describe()
            else:
                notes = th.parse_notes(raw)
                caption = " ".join(th.midi_to_name(n) for n in notes)
        except th.ParseError as exc:
            # Say what was wrong, not just that something was: the notation is
            # the part people get wrong, and a bare refusal teaches nothing.
            yield event.plain_result(f"❌ {exc}\n试试 `/和弦 Cmaj7` 或 `/单音 C4 E4 G4`")
            return

        try:
            signal = synth.render_notes(notes, self.duration, waveform)
            await self._send_voice(
                origin, signal,
                msg_id=str(event.message_obj.message_id or "") or None)
        except Exception as exc:
            logger.exception("[Chord] Failed to synthesise")
            yield event.plain_result(f"合成失败：{type(exc).__name__}: {exc}")
            return
        logger.info("[Chord] %s -> %s", raw, caption)
