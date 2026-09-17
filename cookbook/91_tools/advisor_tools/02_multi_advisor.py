"""
Multiple Advisors
=================
Give the agent several advisors, each with a description of what it is good
at. The agent can pick the right advisor for the question with `ask_advisor`,
or poll all of them at once with `ask_all_advisors`.

This is useful when you want diverse perspectives:
- Different models have different strengths and biases
- Consensus across advisors increases confidence
- Disagreements highlight areas that need attention
"""

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.models.openai import OpenAIResponses
from agno.tools.advisor import AdvisorTools

# ---------------------------------------------------------------------------
# Create Agent with multiple advisors
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[
        AdvisorTools(
            advisors=[
                Claude(id="claude-sonnet-4-6"),
                Gemini(id="gemini-3.5-flash"),
            ],
            descriptions={
                "claude-sonnet-4-6": "Strong at code review and careful reasoning",
                "gemini-3.5-flash": "Fast, strong at long-context analysis and research",
            },
        )
    ],
    instructions=[
        "After drafting a response, use ask_all_advisors to get opinions from all advisors.",
        "Where the advisors agree, the feedback is likely valid.",
        "Where they disagree, use your best judgment.",
        "Provide your final answer incorporating the strongest suggestions.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.print_response(
        "What are the pros and cons of microservices vs monolithic architecture?",
        stream=True,
    )
