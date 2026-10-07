"""Fitting a summary to ``compacted_token_budget`` by dropping whole items, least important first.

A model told to write N tokens cannot count them, so a summary often comes back well over budget.
Cutting the text at N would drop the end of it, and the end is where the summary keeps what matters
most for carrying on: in-progress work, exact identifiers, and the "Not covered here:" line that
tells the agent to search the stored messages. A cut can also land mid-identifier, leaving
something that looks like data but is wrong.

So the summary is trimmed by section instead. Whole items go - a bullet with its sub-bullets, or a
paragraph - from the sections the agent least needs to carry on, oldest first, until it fits. The
sections it needs to carry on are trimmed only if that is not enough.
"""

import re
from typing import Callable, List, Optional, Tuple

NOT_COVERED = "Not covered here:"

# Trimmed first, in this order: history the agent rarely needs to carry on. Matched against the
# lower-cased heading text, so a model that words a heading slightly differently still matches.
_TRIM_FIRST = ("completed", "errors", "key decisions")
# Trimmed last: what the agent needs to carry on. Among these the section with the most items left
# loses one first, so no section is emptied while another keeps a long list; ties go in this order,
# keeping the goal longest. Critical context comes first among equals because its identifiers are
# the easiest thing to find again by searching the stored messages.
_TRIM_LAST = ("critical context", "constraints", "in progress", "goal")

_HEADING = re.compile(r"^#{1,6}\s")
# A top-level bullet starts at the margin; an indented one is a sub-point of the bullet above it.
_BULLET = re.compile(r"^(?:[-*+]|\d+[.)])\s")


class _Section:
    def __init__(self, heading: Optional[str]) -> None:
        self.heading = heading
        # Lines in front of the first item: kept, they are not an item to drop.
        self.lead: List[str] = []
        self.items: List[List[str]] = []

    def tier(self) -> int:
        name = (self.heading or "").lstrip("#").strip().lower()
        if any(name.startswith(key) for key in _TRIM_FIRST):
            return 0
        if any(name.startswith(key) for key in _TRIM_LAST):
            return 2
        # Headings the default prompt does not use, and text outside any heading.
        return 1

    def order(self) -> int:
        name = (self.heading or "").lstrip("#").strip().lower()
        keys = _TRIM_FIRST if self.tier() == 0 else _TRIM_LAST
        return next((i for i, key in enumerate(keys) if name.startswith(key)), len(keys))


def _parse(lines: List[str]) -> List[_Section]:
    sections = [_Section(None)]
    after_blank = True
    for line in lines:
        if _HEADING.match(line):
            sections.append(_Section(line))
            after_blank = True
            continue
        section = sections[-1]
        if not line.strip():
            (section.items[-1] if section.items else section.lead).append(line)
            after_blank = True
            continue
        # An item opens at a top-level bullet, or at an unindented line that starts a paragraph.
        # Indented lines and a paragraph's following lines belong to the item above them.
        opens = bool(_BULLET.match(line)) or (after_blank and not line.startswith((" ", "\t")))
        if opens or not section.items:
            if opens:
                section.items.append([line])
            else:
                section.lead.append(line)
        else:
            section.items[-1].append(line)
        after_blank = False
    return sections


def _render(sections: List[_Section], tail: List[str]) -> str:
    lines: List[str] = []
    for section in sections:
        if section.heading is not None:
            # A heading whose items are all gone says nothing, and its tokens are better spent on
            # an item from another section.
            if not section.items and not any(line.strip() for line in section.lead):
                continue
            lines.append(section.heading)
        lines.extend(section.lead)
        for item in section.items:
            lines.extend(item)
    text = "\n".join(lines).rstrip()
    return "\n\n".join(part for part in [text, *tail] if part)


def fit_summary(summary: str, budget: int, count: Callable[[str], int], note: str) -> Tuple[str, int]:
    """``summary`` cut to at most ``budget`` tokens by dropping whole items, and how many went.

    ``count`` measures text in tokens; ``note`` is appended once anything is dropped, so the agent
    knows the summary has gaps rather than trusting it as complete.
    """
    if count(summary) <= budget:
        return summary, 0

    lines = summary.splitlines()
    not_covered = [line.strip() for line in lines if line.strip().startswith(NOT_COVERED)]
    sections = _parse([line for line in lines if not line.strip().startswith(NOT_COVERED)])
    # The note and the "Not covered here:" line close the summary, whatever else is dropped.
    tail = [note] + not_covered[-1:]

    removed: List[Tuple[_Section, List[str]]] = []
    for tier in (0, 1, 2):
        in_tier = sorted((s for s in sections if s.tier() == tier), key=lambda s: s.order())
        while any(s.items for s in in_tier):
            if tier == 2:
                # The longest list loses an item first; ties go in _TRIM_LAST order.
                section = max(in_tier, key=lambda s: (len(s.items), -s.order()))
            else:
                section = next(s for s in in_tier if s.items)
            # Oldest first: within a section the summary lists items in the order they happened.
            removed.append((section, section.items.pop(0)))
            text = _render(sections, tail)
            if count(text) <= budget:
                return _refill(sections, tail, removed, budget, count)

    # Even with every item gone the closing lines do not fit, which only a budget of a few dozen
    # tokens can cause. Cut whole lines from the end until it does, so the cap still holds.
    text = _render(sections, tail)
    while len(text) > 1 and count(text) > budget:
        cut = text.rfind("\n", 0, len(text) - 1)
        # A single long line has no break to cut at, so shorten it instead.
        text = text[:cut].rstrip() if cut > 0 else text[: len(text) * 9 // 10]
    return text, len(removed)


def _refill(
    sections: List[_Section],
    tail: List[str],
    removed: List[Tuple[_Section, List[str]]],
    budget: int,
    count: Callable[[str], int],
) -> Tuple[str, int]:
    """Put back what still fits, once the summary does.

    The item that made the summary fit can be a large one, leaving room that smaller items dropped
    before it would fill. Most recently dropped first - the trimming order makes those the most
    important. Each goes back to the front of its section, which restores the original order of
    what is kept.
    """
    text = _render(sections, tail)
    dropped = len(removed)
    for section, item in reversed(removed):
        section.items.insert(0, item)
        candidate = _render(sections, tail)
        if count(candidate) <= budget:
            text, dropped = candidate, dropped - 1
        else:
            section.items.pop(0)
    return text, dropped
