#!/usr/bin/env python3
"""List files in a directory."""

import json
import os
import sys

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

if len(sys.argv) < 2:
    path = "."
else:
    path = sys.argv[1]

try:
    entries = []
    for entry in os.listdir(path):
        full_path = os.path.join(path, entry)
        entries.append(
            {
                "name": entry,
                "is_dir": os.path.isdir(full_path),
                "size": os.path.getsize(full_path)
                if os.path.isfile(full_path)
                else None,
            }
        )

    result = {
        "path": os.path.abspath(path),
        "count": len(entries),
        "entries": sorted(entries, key=lambda x: (not x["is_dir"], x["name"])),
    }
    print(json.dumps(result, indent=2))
except Exception as e:
    print(json.dumps({"error": str(e)}))
    sys.exit(1)

# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    raise SystemExit("This module is intended to be imported.")
