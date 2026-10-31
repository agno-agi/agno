"""The regex scan for ``search_result``, run as a script in its own process.

``re`` has no timeout and a thread stuck in the regex engine cannot be
interrupted, so a pattern that backtracks catastrophically would hold the GIL
and wedge the whole process. ResultStore runs this file with
``python -I -c``-free isolation (``python -I <this file>``) and kills it at a
deadline. Isolated mode keeps the working directory and the user site
directory off ``sys.path``: the child imports the standard library only, never
agno and never the caller's code, and a caller script without an
``if __name__ == "__main__"`` guard is not re-executed the way a
``multiprocessing`` spawn worker would re-execute it.

The request arrives on stdin as one JSON document and the reply leaves on
stdout as another. Only match positions cross; the caller renders the text.
ResultStore also imports the position finder and the excerpt window from this
module, so the in-process scan and the subprocess scan find the same positions
and skip the same already-visible matches.
"""

import json
import re
import sys
from typing import List, Tuple


def _match_window(line: str, char_offset: int, match_len: int, clip: int) -> Tuple[int, int]:
    """Character bounds of the excerpt rendered around a match."""
    if len(line) <= clip:
        return 0, len(line)
    width = clip - 6
    lead = width // 4
    start = max(0, min(char_offset - lead, len(line) - width))
    need_end = char_offset + min(max(match_len, 1), width)
    if start + width < need_end:
        start = min(need_end - width, len(line) - width)
    return start, start + width


def _find_match_positions(
    lines: List[str], compiled: "re.Pattern[str]", limit: int, clip: int
) -> Tuple[List[Tuple[int, int, int]], bool]:
    """Return bounded excerpts, skipping matches already visible in an earlier one."""
    positions: List[Tuple[int, int, int]] = []
    for index, line in enumerate(lines):
        covered_end = -1
        for found in compiled.finditer(line):
            if found.end() <= covered_end:
                continue
            if len(positions) >= limit:
                return positions, True
            match_len = found.end() - found.start()
            positions.append((index + 1, found.start(), match_len))
            _, covered_end = _match_window(line, found.start(), match_len, clip)
            if covered_end >= len(line):
                # The excerpt shows the rest of the line; no later match on it can be new.
                break
    return positions, False


def main() -> None:
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    positions, more = _find_match_positions(
        request["content"].split("\n"), re.compile(request["pattern"]), int(request["limit"]), int(request["clip"])
    )
    print(json.dumps({"positions": positions, "more": more}))


if __name__ == "__main__":
    main()
