"""Serve the Team Brain: mint one token per teammate, then start the MCP endpoint."""

import os
import sys
from pathlib import Path

# Serve from this folder no matter where the command was typed: tmp/ and the
# uvicorn import string both resolve against it.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.chdir(HERE)

from team_brain import agent_os, issue_token  # noqa: E402

for teammate in ["alice", "bob"]:
    print(f"{teammate} token: {issue_token(teammate)}")
print("MCP endpoint: http://localhost:7777/mcp (send a token as a bearer header)")
agent_os.serve(app="team_brain:app", port=7777)
