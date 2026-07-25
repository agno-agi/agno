"""Serve the Metrics Desk as an MCP endpoint on http://localhost:7777/mcp."""

import os
import sys
from pathlib import Path

# Serve from this folder no matter where the command was typed: tmp/ and the
# uvicorn import string both resolve against it.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.chdir(HERE)

from metrics_desk import agent_os  # noqa: E402

agent_os.serve(app="metrics_desk:app")
