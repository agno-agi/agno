"""Check Agno's documented case-insensitive substring contract at edge cases.

This is a correctness probe, not a cross-framework ranking: competitors' grep
and the explicit list/read fallback have different case-folding contracts.
"""

import argparse
import json
from pathlib import Path
import tempfile

from adapters import Adapter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix="agno-search-contract-"))
    corpus = {
        "ascii.txt": "Alpha Bravo",
        "unicode.txt": "CAFÉ 東京",
        "kelvin.txt": "Kelvin",
        "literal.txt": "value 50%_done",
        "decoy.txt": "value 50xxdone",
    }
    queries = ["alpha", "café", "東京", "kelvin", "%_", "absent"]
    output = []
    for name in ["agno-local", "agno-sqlite"]:
        adapter = Adapter(name, root / name)
        for path, text in corpus.items():
            adapter.write(path, text)
        for query in queries:
            expected = sorted(
                path for path, text in corpus.items() if query.lower() in text.lower()
            )
            actual = adapter.search(query)
            output.append(
                {
                    "backend": name,
                    "query": query,
                    "expected": expected,
                    "actual": actual,
                    "pass": actual == expected,
                }
            )
        adapter.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(json.dumps(output, ensure_ascii=False, indent=2))
    if not all(row["pass"] for row in output):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
