"""
Agent with Antigravity tools

This example shows how to use Agno's integration with Google's Gemini Agents API
(Antigravity) as a tool. The Agno agent's brain (Gemini, here) decides when to
delegate a sub-task to a managed Antigravity sandbox, which runs an autonomous
loop with web search, code execution, and file I/O built in.

The sandbox persists across calls within the same Agno session, so subsequent
calls can build on prior files and state.

1. Get a Gemini API key enrolled in the Agents API EAP.
2. Set the API key as an environment variable:
    export GEMINI_API_KEY=<your_api_key>
3. Install the dependencies:
    uv pip install agno google-genai
"""

from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.antigravity import AntigravityTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    name="Research Assistant with Antigravity tools",
    model=Gemini(id="gemini-2.5-pro"),
    tools=[AntigravityTools()],
    markdown=True,
    instructions=[
        "You have access to a managed Antigravity sandbox with web search, code execution, and file I/O.",
        "When the user asks for something that benefits from those capabilities — multi-step research, "
        "analysing a repo, generating files, or running code you cannot run locally — delegate the work "
        "to the sandbox via the run_antigravity_task tool.",
        "Otherwise, answer directly without invoking the tool.",
        "The sandbox persists across calls in the same session, so follow-up tasks can build on prior state.",
    ],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Use the Antigravity sandbox to find the latest stable Python release "
        "and summarize what changed in it."
    )
