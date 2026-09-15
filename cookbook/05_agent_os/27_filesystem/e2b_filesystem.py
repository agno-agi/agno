"""
AgentOS E2B Sandbox File System
==============================

Run AgentOS locally while its agent reads and writes files in an E2B sandbox.
The backend adapter lives beside this example; it is not a built-in Agno backend.

Prerequisites: OPENAI_API_KEY, E2B_API_KEY, and e2b>=2.5,<3
Run: .venvs/demo/bin/python cookbook/05_agent_os/27_filesystem/e2b_filesystem.py
Try: Connect Agno OS to http://localhost:7778 and open File System.

Files last only for this sandbox's lifetime. Stopping the example kills the
sandbox; its 30-minute timeout also limits the lifetime if the process crashes.
"""

import os

from e2b import Sandbox
from e2b_backend import E2BFileSystem

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

if __name__ == "__main__":
    if not os.getenv("E2B_API_KEY") or not os.getenv("OPENAI_API_KEY"):
        raise ValueError("Set E2B_API_KEY and OPENAI_API_KEY before starting this example")

    # Create exactly one sandbox for this demo and clean it up on normal exit.
    sandbox = Sandbox.create(timeout=1800)
    try:
        db = SqliteDb(id="e2b-filesystem-db", db_file="tmp/e2b-filesystem-sessions.db")
        filesystem = FileSystem(
            backend=E2BFileSystem(sandbox),
            namespace="sandbox-workspace",
            max_file_bytes=100_000,
            max_namespace_bytes=1_000_000,
        )
        filesystem.write(
            "notes/project.md",
            "# Project\nBuild a documentation assistant with clear setup instructions and source citations.\n",
        )
        agent = Agent(
            id="e2b-filesystem-agent",
            name="E2B File System Agent",
            model=OpenAIResponses(id="gpt-5.6-luna"),
            db=db,
            filesystem=filesystem,
            instructions=[
                "Use your filesystem to read project notes and save reports.",
                "These files live in a temporary E2B sandbox. They disappear when it stops or expires; "
                "do not describe them as durable across sandbox restarts.",
            ],
            markdown=True,
        )
        agent_os = AgentOS(
            id="e2b-filesystem-os",
            description="A local demo with files stored in a temporary E2B sandbox.",
            db=db,
            agents=[agent],
        )
        print(f"E2B sandbox: {sandbox.sandbox_id}")
        print("Connect Agno OS to http://localhost:7778. The sandbox expires after 30 minutes.")
        # Pass the app directly: reload/import workers must not create extra sandboxes.
        agent_os.serve(app=agent_os.get_app(), host="127.0.0.1", port=7778, reload=False)
    finally:
        sandbox.kill()
