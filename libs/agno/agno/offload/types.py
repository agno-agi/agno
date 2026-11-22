"""Result types for tool-result offloading."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Tools whose own output is already capped and must never be offloaded. They
# are also exempt from the tool call limit: they exist because offloading
# replaced a result the model was told to go and read.
NEVER_OFFLOADED_TOOLS = ("read_result", "search_result")


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
    """One bounded page of a stored result.

    A page ends at a line boundary when it can. When a single line is longer
    than one page, the page ends inside that line and ``next_start_char`` says
    where in ``next_start_line`` the next page begins, so every character of
    a stored result can be read back.
    """

    text: str
    start_line: int
    end_line: int
    line_count: int
    truncated: bool
    next_start_line: Optional[int]
    next_start_char: int = 0


@dataclass
class ResultMatch:
    """One search hit inside a stored result.

    ``line`` is the matching line clipped to 500 characters; with
    ``context_lines`` it becomes the surrounding block, one clipped line per
    row, each row prefixed with its own line number, joined with newlines.
    """

    line_number: int
    line: str
    # Character offset of the match in its line. A line longer than the clip
    # is shown as a window around the match, and the offset is where to
    # continue reading with read_result(start_char=...).
    char_offset: int = 0
    # True on the last match when the scan stopped before the end of the
    # payload, at the match cap or the reply budget, so more may follow.
    more: bool = False


__all__ = ["NEVER_OFFLOADED_TOOLS", "ResultMatch", "ResultPage", "ResultRef"]
