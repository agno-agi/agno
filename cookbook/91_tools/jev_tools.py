"""
Jev Tools
=========

Demonstrates `JevTools`, which lets a generative agent ask Jev for typed judgments.

Jev, TypeSafe's System One model, does not write text. It answers typed questions about a
piece of content with calibrated probabilities, in roughly a tenth of a second. Here the agent
writes the questions itself with the `ask_jev` tool: it decides what is worth measuring, Jev
measures it, and the agent reasons over numbers instead of guessing.

This is the shape of a feature-discovery loop: a generative model proposes questions, Jev turns
free text into comparable values, and the results come back as data.

The toolkit adds instructions that teach the agent how to write good Jev questions.

Requirements:
- `pip install typesafe-sdk openai` (Python 3.10+)
- export TYPESAFE_API_KEY="your_api_key"   (https://console.typesafe.ai/keys)
- export OPENAI_API_KEY="your_api_key"
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.typesafe import JevTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    tools=[JevTools()],
    instructions=[
        "You compare pieces of text by measuring them, not by impression.",
        "Decide which qualities matter for the user's question, measure each text on the same questions with ask_jev, "
        "then answer from the numbers and show them in a table.",
    ],
    markdown=True,
)

REVIEWS = """\
A: "Battery lasts two days and the screen is gorgeous. Pricey, but I'd buy it again."
B: "Stopped charging after three weeks. Support took ten days to reply. Avoid."
C: "Fine for calls and email. Camera is mediocre. You get what you pay for."
"""

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.print_response(
        f"Here are three phone reviews:\n{REVIEWS}\n"
        "Which reviewer is most likely to return the phone, and which qualities drive that?",
        stream=True,
        show_full_reasoning=True,
    )
