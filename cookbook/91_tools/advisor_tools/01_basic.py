"""
Basic Advisor
=============
The simplest usage of AdvisorTools: give your agent a single advisor model
it can ask for feedback, a second opinion, or additional context.

How it works:
1. The primary agent (OpenAI) drafts a response
2. It calls `ask_advisor` with a specific question and relevant context
3. The advisor (Gemini) answers without seeing the rest of the conversation
4. The primary agent decides what to incorporate into its final answer

Unlike a critique loop, the agent stays in control: advisor responses are
advice, not instructions.
"""

from agno.agent import Agent
from agno.models.google import Gemini
from agno.models.openai import OpenAIResponses
from agno.tools.advisor import AdvisorTools

# ---------------------------------------------------------------------------
# Create Agent with a single Gemini advisor
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[
        AdvisorTools(
            advisors=[Gemini(id="gemini-3.5-flash")],
        )
    ],
    instructions=[
        "After drafting a response, ask your advisor for a second opinion.",
        "Incorporate the suggestions you agree with into your final answer.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.print_response(
        "Explain how DNS resolution works when you type a URL in your browser",
        stream=True,
    )
