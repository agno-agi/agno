"""
GPT-6 Reasoning
===============

Stream a GPT-6 Astra response and its reasoning summary using the Responses API.
Set OPENAI_API_KEY before running this example.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses


# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------
def run_example() -> None:
    agent = Agent(
        model=OpenAIResponses(
            id="gpt-6-astra",
            reasoning_effort="medium",
            reasoning_summary="auto",
        ),
        markdown=True,
    )

    agent.print_response(
        "Four people need to cross a bridge at night. They take 1, 2, 5, and 10 "
        "minutes to cross. At most two people can cross at once, and they must "
        "carry the only flashlight. When two people cross together, they move "
        "at the slower person's pace. The flashlight must be carried back "
        "whenever people remain on the starting side. Find the minimum total "
        "time and give a crossing schedule with a brief explanation of why "
        "it is optimal.",
        stream=True,
        stream_events=True,
    )


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_example()
