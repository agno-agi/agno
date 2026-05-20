"""
Download an Antigravity sandbox snapshot through AntigravityTools.

`download_antigravity_environment_snapshot` hits the Files API endpoint:
    GET /v1beta/files/environment-{env_id}:download?alt=media

Pass `environment_id="current"` to resolve the env id from the calling Agno
agent's `session_state` — it's set there by a prior `run_antigravity_task` call
within the same session.

Useful for letting an Agno agent introspect or archive what the Antigravity
sandbox produced during a task.

Requirements:
    export GEMINI_API_KEY=...
    uv pip install agno google-genai

Usage:
    .venvs/demo/bin/python cookbook/91_tools/antigravity/antigravity_snapshot_tools.py
"""

import tarfile
from pathlib import Path

from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.antigravity import AntigravityTools

OUT_PATH = Path("tmp/antigravity_snapshot_from_tools.tar")
OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

agent = Agent(
    name="Snapshot Demo",
    model=Gemini(id="gemini-2.5-pro"),
    tools=[AntigravityTools()],
    markdown=True,
    instructions=[
        "Step 1: Use run_antigravity_task to ask the sandbox to create a few files under /workspace/ "
        "(e.g. notes.txt with 'hello', summary.md with a brief intro).",
        f"Step 2: Use download_antigravity_environment_snapshot with environment_id='current' and "
        f"output_path='{OUT_PATH}' to save the snapshot tar.",
        "Step 3: Tell the user where the tar was saved.",
    ],
)

if __name__ == "__main__":
    agent.print_response(
        "Have the sandbox create a couple of files under /workspace, then archive the environment to disk."
    )

    if OUT_PATH.exists():
        print(f"\nSnapshot saved: {OUT_PATH} ({OUT_PATH.stat().st_size} bytes)")
        with tarfile.open(OUT_PATH, "r") as tf:
            members = tf.getnames()
            print(f"Archive contains {len(members)} entries. First 10:")
            for name in members[:10]:
                print(f"  {name}")
