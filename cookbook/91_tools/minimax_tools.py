"""
MiniMax Tools
=============================

Demonstrates MiniMax video generation tools.

The toolkit submits a text-to-video task to the MiniMax video generation API,
polls it until it reaches a terminal state, and returns the result as a Video
artifact.

Setup:
    export MINIMAX_API_KEY=***

Prompts to try:
    - "Generate a video of a paper boat crossing a moonlit lake"
    - "Create a 10 second video of a hot air balloon over a desert at sunrise"
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.minimax import MiniMaxTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

minimax_agent = Agent(
    name="MiniMax Video Generator Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        MiniMaxTools(
            # Use region="cn_zh" for the mainland China endpoint.
            region="global_en",
            model="MiniMax-H3",
        )
    ],
    description="You are an AI agent that can generate videos using the MiniMax API.",
    instructions=[
        "When the user asks you to create a video, use the `generate_video` tool.",
        "Duration is given in whole seconds, from 4 through 15.",
        "Return the URL as raw to the user.",
        "Don't convert video URL to markdown or anything else.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    minimax_agent.print_response(
        "Generate a video of a paper boat crossing a moonlit lake"
    )

    # ---------------------------------------------------------------------------
    # More Examples
    # ---------------------------------------------------------------------------

    # Vertical 9:16 output at a specific duration.
    # minimax_agent.print_response(
    #     "Create a 10 second vertical video of a hot air balloon over a desert at sunrise"
    # )
