"""
Antigravity with pre-loaded environment sources.

Demonstrates seeding the sandbox at provisioning time with files from
GCS, a Git repository, or inline content. The agent can then immediately
read/operate on those files.

Requirements:
    export GEMINI_API_KEY=...

Usage:
    .venvs/demo/bin/python cookbook/frameworks/antigravity/antigravity_sources.py
"""

from agno.agents.antigravity import AntigravityAgent

agent = AntigravityAgent(
    name="Antigravity with Sources",
    sources=[
        # Inline content: small files dropped straight into the sandbox
        {
            "type": "inline",
            "content": "agno is an open-source agent framework",
            "target": "/workspace/about.txt",
        },
        # Repository: clone a Git repo into a target path
        # {"type": "repository", "source": "github://agno-agi/agno", "target": "/workspace/agno"},
        # GCS: pull a folder from a public GCS bucket
        # {"type": "gcs", "source": "gs://my-bucket/data/", "target": "/workspace/data"},
    ],
)

agent.print_response(
    "List the files under /workspace and show the contents of about.txt.",
    stream=True,
)
