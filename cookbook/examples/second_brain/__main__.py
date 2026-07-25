"""Serve the Second Brain as an AgentOS: REST on /, MCP on /mcp."""

import os
import sys
from pathlib import Path

# Serve from this folder no matter where the command was typed: tmp/ and the
# uvicorn import string both resolve against it.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.chdir(HERE)

from second_brain import agent_os  # noqa: E402

agent_os.serve(app="second_brain:app", reload=True)
