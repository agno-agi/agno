"""Attribute streaming recognition results to microphone turns by audio time."""

import asyncio
import time
from abc import abstractmethod
from collections import deque
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Deque, Dict, List, Optional, Tuple

from agno.voice.base import SAMPLE_RATE, STTSession, Transcript


@dataclass
class _Turn:
    start: float
    end: float
    finals: List[str] = field(default_factory=list)
    interim: str = ""


class _TurnTimeline:
    """Track which part of the provider's audio stream belongs to each turn.

    The pipe only streams audio while the user speaks, so every sample sent to
    the provider belongs to exactly one turn, apart from optional padding that
    is recorded as silence. Providers report results in stream time, which maps
    each result to its turn even when the next turn starts before the previous
    turn's final transcript arrives.
    """

    def __init__(self, join: str = " ") -> None:
        self._join = join
        self._sent = 0
        self._turns: Dict[int, _Turn] = {}
        self._order: List[int] = []
        self._committed: Deque[Tuple[int, float]] = deque()

    @property
    def seconds_sent(self) -> float:
        return self._sent / SAMPLE_RATE

    def add_audio(self, turn_id: int, samples: int) -> None:
        now = self.seconds_sent
        if turn_id not in self._turns:
            self._turns[turn_id] = _Turn(start=now, end=now)
            self._order.append(turn_id)
        self._sent += samples
        self._turns[turn_id].end = self.seconds_sent

    def add_silence(self, samples: int) -> None:
        self._sent += samples

    def commit(self, turn_id: int, timeout: float) -> None:
        if turn_id not in self._turns:
            raise ValueError("Cannot commit a turn without microphone audio.")
        self._committed.append((turn_id, time.monotonic() + timeout))

    def turn_at(self, seconds: float) -> Optional[int]:
        # Results can start slightly before a turn's first sample because of
        # pre-roll and model alignment, so take the last turn started by then.
        found: Optional[int] = None
        for turn_id in self._order:
            if self._turns[turn_id].start <= seconds + 0.05:
                found = turn_id
        if found is None and self._order:
            found = self._order[0]
        return found

    def add_final(self, turn_id: Optional[int], text: str) -> Optional[Transcript]:
        turn = self._turns.get(turn_id) if turn_id is not None else None
        if turn_id is None or turn is None or not text:
            return None
        turn.finals.append(text)
        turn.interim = ""
        return Transcript(turn_id=turn_id, text=self._text(turn))

    def set_interim(self, turn_id: Optional[int], text: str) -> Optional[Transcript]:
        turn = self._turns.get(turn_id) if turn_id is not None else None
        if turn_id is None or turn is None or turn.interim == text:
            return None
        turn.interim = text
        return Transcript(turn_id=turn_id, text=self._text(turn))

    def open_turns(self) -> List[int]:
        """Turns not yet completed, oldest first."""
        return list(self._order)

    def is_committed(self, turn_id: int) -> bool:
        return any(committed == turn_id for committed, _ in self._committed)

    def end_of(self, turn_id: int) -> float:
        return self._turns[turn_id].end

    def interim_turns(self) -> List[int]:
        return [turn_id for turn_id in self._order if self._turns[turn_id].interim]

    def finish_through(self, seconds: float) -> List[Transcript]:
        """Complete committed turns whose audio the provider has fully finalized."""
        done: List[Transcript] = []
        if seconds <= 0:
            # Nothing finalized yet; the tolerance must not complete a short turn.
            return done
        while self._committed and self._turns[self._committed[0][0]].end <= seconds + 0.05:
            done.append(self._finish(self._committed.popleft()[0]))
        return done

    def finish_expired(self) -> List[Transcript]:
        """Complete committed turns whose provider finalization did not arrive in time."""
        done: List[Transcript] = []
        now = time.monotonic()
        while self._committed and self._committed[0][1] <= now:
            done.append(self._finish(self._committed.popleft()[0]))
        return done

    def next_deadline(self) -> Optional[float]:
        if not self._committed:
            return None
        return max(0.0, self._committed[0][1] - time.monotonic())

    def _finish(self, turn_id: int) -> Transcript:
        turn = self._turns.pop(turn_id)
        self._order.remove(turn_id)
        text = self._join.join(part for part in turn.finals if part).strip()
        return Transcript(turn_id=turn_id, text=" ".join(text.split()), is_final=True)

    def _text(self, turn: _Turn) -> str:
        parts = [*turn.finals, turn.interim] if turn.interim else turn.finals
        return " ".join(self._join.join(part for part in parts if part).split())


class _TimelineSession(STTSession):
    """A WebSocket recognition session that finalizes turns by provider audio time.

    Subclasses translate provider messages into transcripts and report how far
    the provider has finalized the stream. A committed turn completes as soon
    as that point passes its last sample, or after ``finalize_timeout`` with the
    text received so far.
    """

    _provider = "Speech recognition"

    def __init__(self, connection: Any, finalize_timeout: float, keepalive_interval: float, join: str) -> None:
        self._connection = connection
        self._finalize_timeout = finalize_timeout
        self._keepalive_interval = keepalive_interval
        self._timeline = _TurnTimeline(join=join)
        self._finalized_through = 0.0
        self._send_lock = asyncio.Lock()
        self._last_send = time.monotonic()
        self._keepalive: Optional[asyncio.Task] = None
        self._wake = asyncio.Event()

    @abstractmethod
    def _audio_payload(self, audio: bytes) -> bytes: ...

    @abstractmethod
    def _keepalive_payload(self) -> str: ...

    @abstractmethod
    def _finalize_payload(self) -> str: ...

    @abstractmethod
    def _parse(self, message: Any) -> List[Transcript]:
        """Return transcripts for one provider message and update ``_finalized_through``."""

    async def _send(self, payload: Any) -> None:
        async with self._send_lock:
            await self._connection.send(payload)
            self._last_send = time.monotonic()

    def _start_keepalive(self) -> None:
        self._keepalive = asyncio.create_task(self._keep_alive())

    async def _keep_alive(self) -> None:
        # The pipe only streams audio while the user speaks, and providers close
        # streams that stay silent for too long.
        while True:
            await asyncio.sleep(self._keepalive_interval / 2)
            if time.monotonic() - self._last_send >= self._keepalive_interval:
                await self._send(self._keepalive_payload())

    async def _stop_keepalive(self) -> None:
        if self._keepalive is not None:
            self._keepalive.cancel()
            await asyncio.gather(self._keepalive, return_exceptions=True)

    async def _send_audio(self, audio: bytes, turn_id: int) -> None:
        if len(audio) % 2:
            raise ValueError("Transcription audio must contain complete PCM16 samples.")
        if not audio:
            return
        self._timeline.add_audio(turn_id, len(audio) // 2)
        await self._send(self._audio_payload(audio))

    async def _commit(self, turn_id: int) -> None:
        self._timeline.commit(turn_id, self._finalize_timeout)
        await self._send(self._finalize_payload())
        # The turn may already be covered by audio the provider finalized.
        self._wake.set()

    def _completed(self) -> List[Transcript]:
        return self._timeline.finish_through(self._finalized_through) + self._timeline.finish_expired()

    async def _events(self) -> AsyncIterator[Transcript]:
        from websockets.exceptions import ConnectionClosed

        receive: Optional[asyncio.Future] = None
        try:
            while True:
                for transcript in self._completed():
                    yield transcript
                # No await separates the check above from clearing the event, so a
                # commit cannot be missed.
                self._wake.clear()
                if receive is None:
                    connection = self._connection
                    receive = asyncio.ensure_future(connection.recv())
                waker = asyncio.ensure_future(self._wake.wait())
                try:
                    done, _ = await asyncio.wait(
                        {receive, waker}, timeout=self._timeline.next_deadline(), return_when=asyncio.FIRST_COMPLETED
                    )
                finally:
                    waker.cancel()
                if receive not in done:
                    continue
                try:
                    raw = receive.result()
                except ConnectionClosed as exc:
                    if self._connection is not connection:
                        continue  # Replaced on purpose by a reconnect.
                    raise RuntimeError(f"{self._provider} closed the connection: {exc}") from exc
                finally:
                    receive = None
                if isinstance(raw, bytes):
                    continue
                for transcript in self._parse(raw):
                    yield transcript
        finally:
            if receive is not None:
                receive.cancel()
                await asyncio.gather(receive, return_exceptions=True)


def _to_16k(numpy: Any, audio: bytes) -> bytes:
    """Resample 24 kHz PCM16 to 16 kHz; a 768-sample frame becomes exactly 512."""
    samples = numpy.frombuffer(audio, dtype="<i2").astype(numpy.float32)
    count = max(1, round(len(samples) * 16000 / SAMPLE_RATE))
    positions = numpy.arange(count) * (SAMPLE_RATE / 16000)
    resampled = numpy.interp(positions, numpy.arange(len(samples)), samples)
    return numpy.clip(numpy.rint(resampled), -32768, 32767).astype("<i2").tobytes()
