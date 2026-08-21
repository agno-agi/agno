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
stdout as another. Only match positions cross; the caller renders the text,
with the same code the in-process scan uses.
"""

import json
import re
import sys
from typing import List


def main() -> None:
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    compiled = re.compile(request["pattern"])
    limit = int(request["limit"])
    positions: List[List[int]] = []
    more = False
    for index, line in enumerate(request["content"].split("\n")):
        found = compiled.search(line)
        if found is None:
            continue
        if len(positions) >= limit:
            more = True
            break
        positions.append([index + 1, found.start(), found.end() - found.start()])
    print(json.dumps({"positions": positions, "more": more}))


if __name__ == "__main__":
    main()
