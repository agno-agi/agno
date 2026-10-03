"""State for one voice call: user turns and agent replies."""

import asyncio
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class _Turn:
    """One stretch of user speech, from VAD start to its final transcript."""

    id: int
    started_at: float = field(default_factory=time.perf_counter)
    stopped_at: Optional[float] = None
    text: Optional[str] = None


@dataclass
class _Reply:
    """One agent reply, and how much of it the listener has actually heard."""

    id: int
    stopped_at: float
    prompt: str
    started_at: float = field(default_factory=time.perf_counter)
    text: str = ""
    heard: str = ""
    sent_samples: int = 0
    played_samples: int = 0
    # (end sample, text) pairs from the speech provider, used to work out what was heard.
    marks: List[Tuple[int, str]] = field(default_factory=list)
    interrupted: bool = False
    # The agent run was still going when interrupted, so Agno stores it as
    # cancelled and leaves it out of later history.
    run_cancelled: bool = False
    interruption_note: str = "The user interrupted the reply."
    playback_started: bool = False
    playback_progress: asyncio.Event = field(default_factory=asyncio.Event)
    task: Optional[asyncio.Task] = None

    def update_heard(self) -> None:
        self.heard = " ".join(text for end, text in self.marks if end <= self.played_samples).strip()


def describe_interruption(reply: _Reply) -> str:
    """Tell the agent what happened to its last reply, for the start of the next turn."""
    # A cancelled run is left out of Agno history, so restate what the user said.
    said = f' The user had said: "{reply.prompt}".' if reply.run_cancelled else ""
    heard = f'they heard only: "{reply.heard}"' if reply.heard else "they heard none of it"
    return f"[Your previous reply was cut off. {reply.interruption_note}{said} Of that reply, {heard}.]"


class _PlaybackStalledError(TimeoutError):
    """The browser stopped acknowledging audio while the send window was full."""
