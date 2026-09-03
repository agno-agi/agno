"""Result types for the CodeMode toolkit."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional

from agno.media import Image


@dataclass
class CellResult:
    """The outcome of one executed cell.

    ``status`` is ``"ok"`` for a clean cell, ``"error"`` for a cell that raised
    (the traceback is in ``traceback``), and ``"aborted"`` when the host stopped
    waiting for the cell (interrupt did not land within the grace window).
    ``truncated`` names the streams that hit the per-stream output cap.
    """

    stdout: str = ""
    stderr: str = ""
    result: Optional[str] = None
    traceback: Optional[str] = None
    status: Literal["ok", "error", "aborted"] = "ok"
    truncated: List[str] = field(default_factory=list)
    execution_count: int = 0
    images: List[Image] = field(default_factory=list)
