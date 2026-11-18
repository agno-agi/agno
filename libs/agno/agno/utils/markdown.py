"""Dependency-free Markdown fence tracking for chunkers and source transforms."""

from __future__ import annotations

import re

FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")

# (delimiter character, opening length, complete opening line). A closing fence
# must use the same character and at least the opening length; shorter runs are
# literal content, which is why four-backtick blocks can safely show ``` fences.
FenceState = tuple[str, int, str]


def advance_code_fence(line: str, opened: FenceState | None) -> tuple[FenceState | None, bool]:
    """Return the next fence state and whether this line opens or closes a fence.

    Start with ``opened=None`` and pass the returned state into the next call.
    A line is code when the previous state is set or this call opens a fence;
    this includes the closing delimiter. Shorter fences, mismatched delimiter
    characters and delimiters with trailing text stay literal inside a block.
    The state retains the opening line so chunkers can reopen split blocks.
    Leading whitespace is accepted for code nested inside Markdown or MDX.
    """
    match = FENCE.match(line)
    if match is None:
        return opened, False
    delimiter, suffix = match.groups()
    if opened is None:
        # Backticks are forbidden in a backtick fence's info string. Treat such
        # a line as prose instead of opening a fence that can never close.
        if delimiter[0] == "`" and "`" in suffix:
            return None, False
        return (delimiter[0], len(delimiter), line), True
    character, length, _ = opened
    if delimiter[0] == character and len(delimiter) >= length and not suffix.strip():
        return None, True
    return opened, False
