"""Result types for tool-result offloading."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ResultRef:
    """A stored tool result: the pointer the transcript holds."""

    result_id: str
    path: str
    tool_name: str
    size_bytes: int
    line_count: int
    content_type: str
    created_at: int


@dataclass
class ResultPage:
    """One bounded page of a stored result."""

    text: str
    start_line: int
    end_line: int
    line_count: int
    truncated: bool
    next_start_line: Optional[int]


@dataclass
class ResultMatch:
    """One search hit inside a stored result.

    ``line`` is the matching line clipped to 500 characters; with
    ``context_lines`` it becomes the surrounding block, one clipped line per
    row, joined with newlines.
    """

    line_number: int
    line: str


__all__ = ["ResultMatch", "ResultPage", "ResultRef"]
