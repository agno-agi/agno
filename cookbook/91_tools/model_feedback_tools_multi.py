"""
Model Feedback Tools - Multi-Model Example
============================================
Get parallel feedback from both Gemini and Claude at the same time.
The agent receives combined critique from multiple perspectives.
"""

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.models.openai import OpenAIChat
from agno.tools.model_feedback import ModelFeedbackTools

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        ModelFeedbackTools(
            models=[
                Gemini(id="gemini-2.0-flash"),
                Claude(id="claude-sonnet-4-5-20250514"),
            ],
            aspects=["accuracy", "completeness", "tone"],
        )
    ],
    instructions=[
        "After drafting a response, use the get_feedback tool to get feedback from multiple models.",
        "Review the feedback from each model and incorporate the best suggestions.",
    ],
    markdown=True,
)

if __name__ == "__main__":
    agent.print_response(
        "What are the pros and cons of microservices vs monolithic architecture?",
        stream=True,
    )
