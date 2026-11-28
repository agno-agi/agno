"""
Custom Advisor System Message
=============================
Shape how advisors respond by overriding the `system_message` sent to them.
This turns a general-purpose advisor into a domain-specific reviewer.

You can also override the toolkit `instructions` shown to the primary agent
to control when and how it consults its advisors.
"""

from agno.agent import Agent
from agno.models.google import Gemini
from agno.models.openai import OpenAIResponses
from agno.tools.advisor import AdvisorTools

# ---------------------------------------------------------------------------
# Create Agent with a domain-specific reviewer advisor
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[
        AdvisorTools(
            advisors=[Gemini(id="gemini-3.5-flash")],
            system_message=(
                "You are a medical content reviewer. Evaluate the text you are given for:\n"
                "1. Scientific accuracy - Are claims supported by current medical consensus?\n"
                "2. Safety - Does the text include appropriate disclaimers?\n"
                "3. Readability - Is it accessible to a general audience?\n"
                "4. Actionability - Does it provide clear next steps?\n"
                "Point out specific problems and suggest concrete fixes."
            ),
        )
    ],
    instructions=[
        "You provide general health information.",
        "Always include a disclaimer to consult a healthcare professional.",
        "After drafting, send your draft to the advisor as context and ask for a review.",
        "Apply the fixes the reviewer suggests before answering.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.print_response(
        "What are the common symptoms of iron deficiency?",
        stream=True,
    )
