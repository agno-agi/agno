#!/usr/bin/env python3
"""Print a sorted directory inventory as JSON."""

import argparse
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Create Directory Inventory
# ---------------------------------------------------------------------------


def create_directory_inventory(path: str) -> dict[str, object]:
    """Describe the direct children of one directory."""
    directory = Path(path).expanduser().resolve()
    entries: list[dict[str, object]] = []
    for entry in directory.iterdir():
        is_file = entry.is_file()
        entries.append(
            {
                "is_dir": entry.is_dir(),
                "name": entry.name,
                "size": entry.stat().st_size if is_file else None,
            }
        )

    entries.sort(key=lambda entry: (not bool(entry["is_dir"]), str(entry["name"])))
    return {
        "count": len(entries),
        "entries": entries,
        "path": str(directory),
    }


# ---------------------------------------------------------------------------
# Run Directory Inventory Script
# ---------------------------------------------------------------------------


def main() -> int:
    """Parse the optional path and write one machine-readable inventory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Directory to inspect (defaults to the current directory).",
    )
    args = parser.parse_args()

    try:
        result = create_directory_inventory(args.path)
    except OSError as exc:
        print(
            json.dumps(
                {"error": str(exc), "path": str(Path(args.path).expanduser())},
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
