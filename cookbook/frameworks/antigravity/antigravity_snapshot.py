"""
Download an Antigravity environment snapshot as a tar file.

After an interaction modifies files in the sandbox, you can pull the resulting
filesystem out as a tar archive via the Files API:
    GET /v1beta/files/environment-{environment_id}:download?alt=media

Useful for inspecting what the agent produced, archiving runs, or seeding a
new environment from a known-good state.

Requirements:
    export GEMINI_API_KEY=...

Usage:
    .venvs/demo/bin/python cookbook/frameworks/antigravity/antigravity_snapshot.py
"""

import tarfile
from pathlib import Path

from agno.agents.antigravity import AntigravityAgent

OUT_PATH = Path("tmp/antigravity_snapshot.tar")
OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
SESSION_ID = "snapshot-demo"

agent = AntigravityAgent(name="Antigravity Snapshot Demo")

# Run something that writes a file into the sandbox. Non-streaming so the
# adapter captures `environment_id` from the response (SSE doesn't carry it).
agent.print_response(
    "Create a file /workspace/hello.txt containing the line 'snapshot test' and confirm it exists.",
    stream=False,
    session_id=SESSION_ID,
)

# Pull the env snapshot for the session we just ran.
bytes_written = agent.download_environment_snapshot(
    str(OUT_PATH),
    session_id=SESSION_ID,
)
print(f"\nSnapshot saved: {OUT_PATH} ({bytes_written} bytes)")

# Inspect the archive.
with tarfile.open(OUT_PATH, "r") as tf:
    members = tf.getnames()
    print(f"Archive contains {len(members)} entries. First 10:")
    for name in members[:10]:
        print(f"  {name}")
