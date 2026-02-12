#!/usr/bin/env python3
"""Get basic system information."""

import json
import platform
import sys
from datetime import datetime

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

try:
    info = {
        "os": platform.system(),
        "os_version": platform.version(),
        "python_version": sys.version,
        "machine": platform.machine(),
        "processor": platform.processor(),
        "current_time": datetime.now().isoformat(),
        "hostname": platform.node(),
    }
except Exception as e:
    info = {"error": str(e)}

print(json.dumps(info, indent=2))

# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    raise SystemExit("This module is intended to be imported.")
