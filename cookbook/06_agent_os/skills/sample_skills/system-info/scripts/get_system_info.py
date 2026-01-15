#!/usr/bin/env python3
"""Get basic system information."""

import json
import platform
import sys
from datetime import datetime

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
