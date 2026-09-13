#!/usr/bin/env python3
"""Print useful host and Python runtime information as JSON."""

import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Create System Information
# ---------------------------------------------------------------------------


def collect_system_info() -> dict[str, str]:
    """Collect portable facts about the current host and Python runtime."""
    return {
        "architecture": platform.machine(),
        "current_time_utc": datetime.now(timezone.utc).isoformat(),
        "hostname": platform.node(),
        "os": platform.system(),
        "os_release": platform.release(),
        "processor": platform.processor(),
        "python_executable": str(Path(sys.executable).resolve()),
        "python_version": platform.python_version(),
    }


# ---------------------------------------------------------------------------
# Run System Information Script
# ---------------------------------------------------------------------------


def main() -> int:
    """Write one machine-readable system information document."""
    print(json.dumps(collect_system_info(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
