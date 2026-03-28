"""
Model Feedback Tools - Basic Example
=====================================
Use a secondary model (Gemini) to critique the primary agent's responses.
The agent gets a "second opinion" before finalizing its answer.
"""

from agno.agent import Agent
from agno.models.google import Gemini
from agno.models.openai import OpenAIChat
from agno.tools.model_feedback import ModelFeedbackTools

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        ModelFeedbackTools(
            model=Gemini(id="gemini-2.0-flash"),
            aspects=["accuracy", "completeness", "tone"],
        )
    ],
    instructions=[
        "After drafting a response, use the get_feedback tool to get a second opinion.",
        "If the feedback suggests improvements, incorporate them into your final answer.",
    ],
    markdown=True,
)

if __name__ == "__main__":
    agent.print_response(
        "Explain the differences between REST and GraphQL APIs",
        stream=True,
    )
