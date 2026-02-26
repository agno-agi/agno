"""
Grounding - Fact-Checked Responses with Citations
===================================================
Grounding enables Gemini to back its responses with real-time web information
and provide citations. Responses are verifiable and fact-based.

Unlike native search (step 4), grounding is specifically designed for
factual accuracy. The model provides grounding metadata you can inspect
to verify claims.

Key concepts:
- grounding=True: Enables Gemini's grounding capability
- grounding_dynamic_threshold: Controls how aggressively grounding kicks in (0.0-1.0)
- Citations: The response includes source metadata for verification
- Grounding vs search: Grounding prioritizes accuracy, search prioritizes breadth

Example prompts to try:
- "What are the current market trends in renewable energy?"
- "What is the population of Tokyo in 2025?"
- "Who won the latest Nobel Prize in Physics?"
- "What are the key provisions of the EU AI Act?"
"""

from agno.agent import Agent
from agno.models.google import Gemini

# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
You are a fact-checking agent. Provide well-sourced, verifiable answers.

## Rules

- Ground all claims in real-time data
- Clearly distinguish facts from analysis
- Cite sources when available\
"""

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
fact_checker = Agent(
    name="Fact Checker",
    model=Gemini(
        id="gemini-3-flash-preview",
        grounding=True,
        # Threshold for when grounding activates (0.0 = always, 1.0 = rarely)
        grounding_dynamic_threshold=0.7,
    ),
    instructions=instructions,
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

# ---------------------------------------------------------------------------
# More Examples
# ---------------------------------------------------------------------------
"""
Grounding threshold controls sensitivity:

- 0.0: Always ground (most citations, slower)
- 0.3: Ground most responses
- 0.7: Ground when model is less confident (good default)
- 1.0: Rarely ground (fastest, fewest citations)

To inspect grounding metadata:

    response = agent.run("What is the GDP of Japan?")
    if response.citations and response.citations.raw:
        metadata = response.citations.raw.get("grounding_metadata", {})
        chunks = metadata.get("grounding_chunks", [])
        for chunk in chunks:
            print(chunk)  # Source URLs and snippets
"""
