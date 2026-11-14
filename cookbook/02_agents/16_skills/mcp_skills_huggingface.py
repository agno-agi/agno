"""
MCP Skills from Hugging Face
=============================

Load skills from Hugging Face's public MCP server, which serves them through the
MCP Skills extension. No API key is needed to list or read them.

The agent sees each skill's name and description, loads the instructions of the
one that matches the question, and verifies every file it reads against the
server's manifest. Skills from the server are namespaced as `hf/<skill>`, and
their scripts can be read but never executed.
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.skills import MCPSkills, Skills

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
huggingface_skills = MCPSkills(url="https://huggingface.co/mcp", label="hf")

agent = Agent(
    name="Hugging Face Assistant",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    skills=Skills(loaders=[huggingface_skills]),
    instructions=[
        "Use your skills to answer questions about the Hugging Face ecosystem."
    ],
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # MCP-served skills load on async runs.
    asyncio.run(
        agent.aprint_response(
            "How do I estimate how much memory a GGUF model needs before loading it?"
        )
    )
