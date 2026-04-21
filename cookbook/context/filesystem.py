"""
Filesystem Context Provider
===========================

Expose a local directory tree to an agent as a read-only context.

Run: pip install openai
Env: OPENAI_API_KEY
"""

from pathlib import Path

from agno.agent import Agent
from agno.context.fs import FilesystemContextProvider
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Build Provider
# ---------------------------------------------------------------------------
# Point at agno's own cookbook folder as a sample directory.
SAMPLE_ROOT = Path(__file__).resolve().parents[1]

provider = FilesystemContextProvider(root=SAMPLE_ROOT)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=provider.get_tools(),
    instructions=[
        "You answer questions about files under the configured root.",
        provider.instructions(),
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Status:", provider.status())
    agent.print_response(
        "Find the README in the context cookbook and summarize what each example shows.",
        stream=True,
    )
