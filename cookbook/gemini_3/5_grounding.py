"""
5. Grounding
============
Grounding enables Gemini to back its responses with real-time web information
and provide citations. Responses are verifiable and fact-based.

Run:
    python cookbook/gemini_3/5_grounding.py

Example prompt:
    "What are the current market trends in renewable energy?"
"""

from agno.agent import Agent
from agno.models.google import Gemini

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
fact_checker = Agent(
    name="Fact Checker",
    model=Gemini(
        id="gemini-3-flash-preview",
        grounding=True,
        grounding_dynamic_threshold=0.7,
    ),
    instructions="""\
You are a fact-checking agent. Provide well-sourced, verifiable answers.

## Rules

- Ground all claims in real-time data
- Clearly distinguish facts from analysis
- Cite sources when available\
""",
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    fact_checker.print_response(
        "What are the current market trends in renewable energy?",
        stream=True,
    )
