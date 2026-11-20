"""
MCP Skills
=============================

Load skills served by an MCP server through the MCP Skills extension.

`mcp_skills_server.py` serves `sample_skills/` over MCP. The agent lists the
server's skills on its first run, then reads `SKILL.md` and supporting files
only when it needs them, verifying each file against the server's manifest.

Skills served over MCP are namespaced by the server label (for example
`review-server/code-review`), tagged with their origin in the model's context,
and their scripts can be read but never executed.
"""

import asyncio
import sys
from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.skills import MCPSkills, Skills

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
server_script = Path(__file__).parent / "mcp_skills_server.py"
review_skills = MCPSkills(
    command=f"{sys.executable} {server_script}", label="review-server"
)

agent = Agent(
    name="Code Review Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    skills=Skills(loaders=[review_skills]),
    instructions=["You are a helpful assistant with access to specialized skills."],
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # MCP-served skills load on async runs.
    asyncio.run(
        agent.aprint_response(
            "Review this Python code and provide feedback:\n\n"
            "```python\n"
            "def calculate_total(items):\n"
            "    total = 0\n"
            "    for i in range(len(items)):\n"
            "        total = total + items[i]['price'] * items[i]['quantity']\n"
            "    return total\n"
            "```"
        )
    )
