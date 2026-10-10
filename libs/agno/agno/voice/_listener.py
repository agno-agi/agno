"""The microphone side of a voice call: speech detection, turns, and transcription."""

import asyncio
import time
from collections import deque
from typing import TYPE_CHECKING, Awaitable, Callable, Deque, Dict, Optional, Tuple

from agno.voice._channel import _ClientChannel
from agno.voice._state import _Turn
from agno.voice.base import STTSession, VADSession

if TYPE_CHECKING:
    from agno.voice.pipe import VoicePipe

# Audio kept from just before speech is detected, so the first syllable is not lost.
_PREROLL_FRAMES = 8


class _Listener:
    """Turn microphone frames into user turns with final transcripts.

    Speech start interrupts any reply in progress; a turn that is complete and
    transcribed asks for a reply. Both are callbacks so this class knows nothing
    about how replies are made.
    """

    def __init__(
        self,
        pipe: "VoicePipe",
        vad: VADSession,
        stt: STTSession,
        channel: _ClientChannel,
        on_speech_started: Callable[[], Awaitable[None]],
        on_turn_ready: Callable[[], Awaitable[None]],
    ) -> None:
        self._pipe, self._vad, self._stt, self._channel = pipe, vad, stt, channel
        self._on_speech_started, self._on_turn_ready = on_speech_started, on_turn_ready
        self._frames: asyncio.Queue = asyncio.Queue(maxsize=pipe.max_audio_frames)
        self._stt_audio: asyncio.Queue = asyncio.Queue(maxsize=pipe.max_audio_frames)
        self._preroll: Deque[bytes] = deque(maxlen=_PREROLL_FRAMES)
        self.turns: Dict[int, _Turn] = {}
        self._turn_id = 0
        self.speaking = False

    def accept_frame(self, pcm: bytes) -> None:
        try:
            self._frames.put_nowait(pcm)
        except asyncio.QueueFull:
            raise RuntimeError("Microphone processing cannot keep up; audio queue limit reached.") from None

    def take_prompt(self) -> Optional[Tuple[str, float]]:
        """Return the user's words and when they stopped, once every pending turn is complete.

        Several turns separated by short pauses are answered together. Returns
        None while the user is still speaking or a transcript is still pending.
        """
        if self.speaking or not self.turns:
            return None
        turns = list(self.turns.values())
        if any(turn.text is None or turn.stopped_at is None for turn in turns):
            return None
        prompt = " ".join(turn.text for turn in turns if turn.text).strip()
        stopped_at = turns[-1].stopped_at or time.perf_counter()
        self.turns.clear()
        return prompt, stopped_at

    def _queue_for_stt(self, audio: Optional[bytes], turn_id: int) -> None:
        # None marks the end of a turn.
        try:
            self._stt_audio.put_nowait((audio, turn_id))
        except asyncio.QueueFull:
            raise RuntimeError("Speech recognition cannot keep up; audio queue limit reached.") from None

    async def listen(self) -> None:
        while True:
            pcm = await self._frames.get()
            was_speaking = self.speaking
            if not was_speaking:
                self._preroll.append(pcm)
            event = await self._vad._process(pcm)
            if event == "start" and not was_speaking:
                # Mark the user as speaking before awaiting anything, so a late
                # final transcript cannot start a reply in the meantime.
                self.speaking = True
                self._turn_id += 1
                self.turns[self._turn_id] = _Turn(self._turn_id)
                await self._on_speech_started()
                await self._channel.send("speech_started", turn_id=self._turn_id)
                for frame in self._preroll:
                    self._queue_for_stt(frame, self._turn_id)
                self._preroll.clear()
            elif was_speaking:
                self._queue_for_stt(pcm, self._turn_id)
            if event == "stop" and self.speaking:
                self.speaking = False
                self.turns[self._turn_id].stopped_at = time.perf_counter()
                self._queue_for_stt(None, self._turn_id)
                await self._channel.send("speech_stopped", turn_id=self._turn_id)
                await self._on_turn_ready()

    async def transmit(self) -> None:
        while True:
            audio, turn_id = await self._stt_audio.get()
            if audio is None:
                await self._stt._commit(turn_id)
            else:
                await self._stt._send_audio(audio, turn_id)

    async def transcripts(self) -> None:
        async for event in self._stt._events():
            turn = self.turns.get(event.turn_id)
            if turn is None or turn.text is not None:
                continue
            kind = "transcript" if event.is_final else "transcript_delta"
            await self._channel.send(kind, turn_id=event.turn_id, text=event.text)
            if event.is_final:
                turn.text = event.text.strip()
                await self._on_turn_ready()
        raise RuntimeError("Speech recognition disconnected.")

    async def watchdog(self) -> None:
        while True:
            await asyncio.sleep(0.25)
            now = time.perf_counter()
            for turn in self.turns.values():
                if turn.stopped_at is None and now - turn.started_at > self._pipe.max_utterance_seconds:
                    raise RuntimeError("Maximum continuous speech duration exceeded.")
                if (
                    turn.stopped_at is not None
                    and turn.text is None
                    and now - turn.stopped_at > self._pipe.transcription_timeout
                ):
                    raise TimeoutError("Speech recognition timed out.")
